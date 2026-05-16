#!/usr/bin/env python3
"""
dict_build_audio.py
===================
For every dictionary entry, ensure an MP3 file exists under
    dictionary/audio/ipay/<slug>.mp3      (Basay TTS,  voice: bsy+f1)
    dictionary/audio/hokkien/<slug>.mp3   (Hokkien TTS, voice: bsystd)

Pipeline (per missing variant):
    espeak-ng → WAV → ffmpeg loudnorm (-16 LUFS) → ffmpeg MP3 64k mono

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

REQUIRES
--------
  - espeak-ng on PATH (with custom Basay/Hokkien voices configured)
  - ffmpeg on PATH
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


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def check_tools() -> None:
    for tool in ("espeak-ng", "ffmpeg"):
        if shutil.which(tool) is None:
            sys.exit(
                f"ERROR: {tool} not found on PATH.\n"
                f"  Debian/Ubuntu: sudo apt install {tool}"
            )


def synth_wav(text: str, voice: str, out_wav: Path) -> None:
    """eSpeak-NG → raw WAV."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["espeak-ng", "-v", voice, text, "-w", str(out_wav)]
    subprocess.run(cmd, check=True, capture_output=True)


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


def generate_one(
    display: str, variant: str, voice: str, slug: str,
    bitrate: str, tmpdir: Path, dry_run: bool,
) -> tuple[bool, str]:
    """Generate a single MP3. Returns (ok, message)."""
    mp3 = AUDIO_ROOT / variant / f"{slug}.mp3"
    if dry_run:
        return True, f"DRY  {variant}/{slug}.mp3"
    try:
        # Use the basay_text-derived TTS text for ipay; for hokkien, the
        # original gen_audio also uses the same TTS text (the voice differs).
        tts_text = basay_text.derive(display)["tts"]
        wav = tmpdir / f"{slug}_{variant}.wav"
        synth_wav(tts_text, voice, wav)
        normalize_wav(wav)
        wav_to_mp3(wav, mp3, bitrate=bitrate)
        try:
            wav.unlink()
        except OSError:
            pass
        return True, f"made {variant}/{slug}.mp3"
    except subprocess.CalledProcessError as e:
        return False, f"FAIL {variant}/{slug}.mp3: {e}"
    except Exception as e:
        return False, f"FAIL {variant}/{slug}.mp3: {e!r}"


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
    args = parser.parse_args()

    if not args.dry_run:
        check_tools()

    entries = load_entries()
    variants = [args.only] if args.only else list(VOICE_MAP.keys())

    AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    for v in variants:
        (AUDIO_ROOT / v).mkdir(parents=True, exist_ok=True)

    plan: list[tuple[str, str, str, str]] = []   # (display, slug, variant, voice)
    skipped = 0
    for e in entries:
        display = e.get("basay", "").strip()
        if not display:
            continue
        slug = basay_text.derive(display)["slug"]
        for variant in variants:
            mp3 = AUDIO_ROOT / variant / f"{slug}.mp3"
            if mp3.is_file() and not args.force:
                skipped += 1
                continue
            plan.append((display, slug, variant, VOICE_MAP[variant]))

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
    with tempfile.TemporaryDirectory(prefix="basay_dict_audio_") as td:
        tmpdir = Path(td)
        for i, (display, slug, variant, voice) in enumerate(plan, start=1):
            ok, msg = generate_one(display, variant, voice, slug,
                                   args.bitrate, tmpdir, dry_run=False)
            tag = "✓" if ok else "✗"
            print(f"  [{i}/{len(plan)}] {tag} {msg}")
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
