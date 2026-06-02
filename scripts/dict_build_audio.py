#!/usr/bin/env python3
"""
dict_build_audio.py
===================
For every dictionary entry, ensure an MP3 file exists under
    dictionary/audio/ipay/<slug>.mp3      (Basay TTS,  voice: bsy+f1)
    dictionary/audio/hokkien/<slug>.mp3   (Hokkien TTS, voice: bsystd)

Pipeline (per missing variant):
    HF Space API (inkuei/basaytts) → WAV → ffmpeg loudnorm (-16 LUFS) → ffmpeg MP3 64k mono

Only the MP3 is committed to git; intermediate WAVs are written to a temp dir.
Existing MP3 files are skipped unless --force is given.

After audio generation, the JSON (`dictionary/entries/*.json` and
`data/dictionary.json`) is refreshed so that each entry carries an `audio`
field pointing at the generated files.

USAGE
-----
  python scripts/dict_build_audio.py
  python scripts/dict_build_audio.py --force                 # re-generate all
  python scripts/dict_build_audio.py --only ipay             # one voice only
  python scripts/dict_build_audio.py --bitrate 48k           # smaller files
  python scripts/dict_build_audio.py --dry-run               # plan, don't run
  python scripts/dict_build_audio.py --id 417-419,523        # specific IDs
  python scripts/dict_build_audio.py --basay "vanan'" "labatan" --force
  python scripts/dict_build_audio.py --slug ranum vatu siya --force

REQUIRES
--------
  - ffmpeg on PATH
  - gradio_client (pip install gradio_client)
  - scripts/basay_text.py importable (uses derive() for slug + TTS text)

NOTE ON DISK USAGE
------------------
  4000 entries × 2 voices × ~20 KB (MP3 64k mono) ≈ 160 MB
  Well within GitHub Pages free-tier limits.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the same helpers / config as the Excel→JSON pipeline.
import basay_text  # noqa: E402
import dict_excel_to_json as dx  # noqa: E402

REPO_ROOT   = dx.REPO_ROOT
AUDIO_ROOT  = dx.AUDIO_ROOT
SITE_JSON   = dx.SITE_JSON

IPAY_VOICE    = os.environ.get("IPAY_VOICE",    "bsy+f1")
HOKKIEN_VOICE = os.environ.get("HOKKIEN_VOICE", "bsystd")

VOICE_MAP = {
    "ipay":    IPAY_VOICE,
    "hokkien": HOKKIEN_VOICE,
}

LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true"


def parse_id_ranges(spec: str) -> set[int]:
    """ID 範囲を集合にする。

    例:
      "1-10,23,25-38,100" → {1,2,...,10,23,25,...,38,100}
      "0417, 0419"        → {417, 419}   （前後空白とゼロパディングを許容）

    不正な入力は ValueError を投げる。
    """
    ids: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo, hi = lo.strip(), hi.strip()
            if not lo or not hi:
                raise ValueError(f"不正な範囲指定: {part!r}")
            ids.update(range(int(lo), int(hi) + 1))
        else:
            ids.add(int(part))
    return ids


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def check_tools() -> None:
    for tool in ("ffmpeg",):  # espeak-ng は Space API を使用
        if shutil.which(tool) is None:
            sys.exit(
                f"ERROR: {tool} not found on PATH.\n"
                f"  Debian/Ubuntu: sudo apt install {tool}"
            )


def make_client():
    """gradio_client.Client を生成して返す（スレッドごとに1つ作成）。"""
    from gradio_client import Client
    return Client("inkuei/basaytts", verbose=False)


def synth_wav(text: str, voice: str, out_wav: Path, client=None) -> None:
    """Space API (inkuei/basaytts) → raw WAV.
    text には basay_text.derive()["tts"] 済みの文字列を渡す。
    Space 側では tts_override として受け取り、二重変換を防ぐ。
    client を渡すと再利用する（並列処理時はスレッドローカルで管理）。
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    voice_short = voice.split("+")[0]  # "bsy+f1" → "bsy"
    c = client or make_client()
    result = c.predict(
        tts_text=text,
        voice_short=voice_short,
        api_name="/synth_wav",
    )
    shutil.copy(result, out_wav)


def normalize_wav(wav: Path) -> None:
    """In-place loudnorm to -16 LUFS."""
    tmp = wav.with_suffix(".norm.wav")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav),
        "-af", LOUDNORM_FILTER,
        str(tmp),
    ]
    subprocess.run(cmd, check=True)
    tmp.replace(wav)


def wav_to_mp3(wav: Path, mp3: Path, bitrate: str = "64k") -> None:
    """WAV → MP3 (mono, configurable bitrate, default 64 kbps)."""
    mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav),
        "-ac", "1",                  # mono
        "-codec:a", "libmp3lame",
        "-b:a", bitrate,
        str(mp3),
    ]
    subprocess.run(cmd, check=True)


def _primary(display: str) -> str:
    """Return the primary form for slug/TTS derivation:
    everything before the first '|', stripped of whitespace.
    Matches dict_excel_to_json.derive_slug() semantics."""
    return display.split("|")[0].strip()


def _slug_letter(slug: str) -> str:
    """Letter subfolder bucket for an audio MP3. Mirrors dict_excel_to_json._slug_letter."""
    if slug:
        first = slug[0].lower()
        if "a" <= first <= "z":
            return first
    return "_misc"


def _mp3_path(variant: str, slug: str) -> Path:
    """New layout: dictionary/audio/<variant>/<letter>/<slug>.mp3."""
    return AUDIO_ROOT / variant / _slug_letter(slug) / f"{slug}.mp3"


def generate_one(
    display: str, variant: str, voice: str, slug: str,
    bitrate: str, tmpdir: Path, dry_run: bool, client=None,
) -> tuple[bool, str]:
    """Generate a single MP3. Returns (ok, message)."""
    mp3 = _mp3_path(variant, slug)
    rel_label = f"{variant}/{_slug_letter(slug)}/{slug}.mp3"
    if dry_run:
        return True, f"DRY  {rel_label}"
    try:
        # Synthesize ONLY the primary form (before '|'), matching the slug.
        # Otherwise we'd speak both variants in one file and the slug→filename
        # detection in dict_excel_to_json wouldn't find it.
        primary = _primary(display)
        tts_text = basay_text.derive(primary)["tts"]
        wav = tmpdir / f"{slug}_{variant}.wav"
        synth_wav(tts_text, voice, wav, client=client)
        normalize_wav(wav)
        wav_to_mp3(wav, mp3, bitrate=bitrate)
        try:
            wav.unlink()
        except OSError:
            pass
        return True, f"made {rel_label}"
    except subprocess.CalledProcessError as e:
        return False, f"FAIL {rel_label}: {e}"
    except Exception as e:
        return False, f"FAIL {rel_label}: {e!r}"


def load_entries() -> list[dict[str, Any]]:
    if not SITE_JSON.is_file():
        sys.exit(
            f"ERROR: {SITE_JSON} not found.\n"
            "Run `python scripts/dict_excel_to_json.py` first."
        )
    with SITE_JSON.open(encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--only", choices=list(VOICE_MAP.keys()),
                        help="Generate only this variant (ipay or hokkien)")
    parser.add_argument("--force", action="store_true",
                        help="Re-generate existing MP3s instead of skipping")
    parser.add_argument("--bitrate", default="64k",
                        help="MP3 bitrate (default: 64k; try 48k for smaller files)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be generated, write nothing")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N generations (useful for testing)")
    parser.add_argument("--workers", type=int, default=4,
                        help="並列ワーカー数（デフォルト: 4）。Space の負荷に応じて調整")
    parser.add_argument("--slug", nargs="+", metavar="SLUG", default=None,
                        help="Only (re)generate audio for these specific slugs. "
                             "Combine with --force to overwrite existing MP3s. "
                             "Example: --slug ranum vatu siya")
    parser.add_argument("--basay", nargs="+", metavar="BASAY", default=None,
                        help="Same as --slug but accepts basay text; the script "
                             "derives slug from each. Useful for ad-hoc updates. "
                             "Example: --basay \"hihol'\" \"kul-apba\"")
    parser.add_argument("--ID", "--id", dest="id_ranges", metavar="RANGES", default=None,
                        help="ID 範囲指定（例: 1-10,23,25-38,100）。"
                             "dictionary.json の id フィールドと照合する。"
                             "--slug / --basay と併用可。"
                             "大文字 --ID / 小文字 --id どちらも同じ。")
    args = parser.parse_args()

    if not args.dry_run:
        check_tools()

    # IMPORTANT: refresh JSON from the latest Excel FIRST so that planning
    # uses the current basay forms. Otherwise edits in Excel since the last
    # excel_to_json run won't trigger MP3 generation.
    print("Refreshing JSON from Excel ...")
    rc = subprocess.call(
        [sys.executable, str(SCRIPT_DIR / "dict_excel_to_json.py")]
    )
    if rc != 0:
        print("  ! excel_to_json failed; aborting audio build", file=sys.stderr)
        return rc
    print()

    entries = load_entries()
    variants = [args.only] if args.only else list(VOICE_MAP.keys())

    # Build filter set from --slug / --basay / --id(--ID)
    slug_filter: set[str] | None = None
    if args.slug:
        slug_filter = set(args.slug)
    if args.basay:
        derived = {basay_text.derive(_primary(b))["slug"] for b in args.basay}
        slug_filter = (slug_filter | derived) if slug_filter else derived
    if args.id_ranges:
        id_set = parse_id_ranges(args.id_ranges)
        id_slugs: set[str] = set()
        skipped_non_numeric = 0
        for e in entries:
            eid = e.get("id", "")
            if not eid:
                continue
            try:
                if int(eid) in id_set:
                    primary = _primary(e.get("basay", ""))
                    if primary:
                        id_slugs.add(basay_text.derive(primary)["slug"])
            except (ValueError, TypeError):
                # "0417a" のような非数値 ID をスキップ
                skipped_non_numeric += 1
                continue
        slug_filter = (slug_filter | id_slugs) if slug_filter else id_slugs
        print(f"--id resolved to {len(id_slugs)} slug(s)"
              + (f" (skipped {skipped_non_numeric} non-numeric IDs)"
                 if skipped_non_numeric else ""))
    if slug_filter:
        print(f"Filtering by {len(slug_filter)} slug(s): {sorted(slug_filter)}")

    AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    for v in variants:
        (AUDIO_ROOT / v).mkdir(parents=True, exist_ok=True)

    plan: list[tuple[str, str, str, str]] = []   # (display, slug, variant, voice)
    skipped = 0
    for e in entries:
        display = e.get("basay", "").strip()
        if not display:
            continue
        # Derive slug from the PRIMARY form only (everything before '|'),
        # to match dict_excel_to_json.derive_slug().
        slug = basay_text.derive(_primary(display))["slug"]
        if slug_filter is not None and slug not in slug_filter:
            continue
        for variant in variants:
            mp3 = _mp3_path(variant, slug)
            # Backward-compat: also count old flat-layout files as "already present"
            # so an unmigrated repo doesn't re-generate everything on first run.
            mp3_flat = AUDIO_ROOT / variant / f"{slug}.mp3"
            if (mp3.is_file() or mp3_flat.is_file()) and not args.force:
                skipped += 1
                continue
            plan.append((display, slug, variant, VOICE_MAP[variant]))

    # 同一 slug+variant が複数エントリーに存在する場合を除去
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str, str, str]] = []
    for item in plan:
        key = (item[1], item[2])  # (slug, variant)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(item)
    plan = deduped

    print(f"{len(entries)} entries; planned {len(plan)} generations, "
          f"{skipped} already present.")

    if args.limit and len(plan) > args.limit:
        print(f"(limiting to first {args.limit})")
        plan = plan[: args.limit]

    if args.dry_run:
        for display, slug, variant, _ in plan[:50]:
            print(f"  DRY {variant}/{slug}.mp3   ← {display!r}")
        if len(plan) > 50:
            print(f"  ... and {len(plan) - 50} more")
        return 0

    failures: list[str] = []
    workers = min(args.workers, len(plan)) if plan else 1
    print(f"  workers={workers}")
    counter_lock = threading.Lock()
    counter = [0]

    _tls = threading.local()

    def _get_client():
        if not hasattr(_tls, "client"):
            _tls.client = make_client()
        return _tls.client

    def _run(item):
        display, slug, variant, voice = item
        c = _get_client()
        ok, msg = generate_one(display, variant, voice, slug,
                               args.bitrate, tmpdir, dry_run=False, client=c)
        with counter_lock:
            counter[0] += 1
            tag = "✓" if ok else "✗"
            print(f"  [{counter[0]}/{len(plan)}] {tag} {msg}", flush=True)
        return ok, msg

    with tempfile.TemporaryDirectory(prefix="basay_dict_audio_") as td:
        tmpdir = Path(td)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_run, item) for item in plan]
            for future in as_completed(futures):
                ok, msg = future.result()
                if not ok:
                    failures.append(msg)

    print()
    print(f"Done. {len(plan) - len(failures)} generated, "
          f"{len(failures)} failed, {skipped} skipped.")
    for f in failures[:20]:
        print(f"  ! {f}", file=sys.stderr)

    # Refresh JSON so that newly-generated audio is reflected in the
    # `audio` field of each entry (excel_to_json scans the filesystem).
    print()
    print("Refreshing JSON to pick up new audio references ...")
    rc = subprocess.call(
        [sys.executable, str(SCRIPT_DIR / "dict_excel_to_json.py")]
    )
    return rc if rc else (1 if failures else 0)


if __name__ == "__main__":
    raise SystemExit(main())
