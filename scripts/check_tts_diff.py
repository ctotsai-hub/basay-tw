#!/usr/bin/env python3
"""
check_tts_diff.py — 旧 TTS（v2）と新 TTS（v3）の差分レポート

============================================================
何をする？
============================================================
audio_manifest.tsv（HTML 由来）と data/daily.json から全 Basay 例文を集め、
  ・display
  ・slug
  ・v2 TTS（旧ルール）
  ・v3 TTS（新ルール、basay_text.py を使用）
  ・wav 存在状況
を一覧表示。差分があるエントリを抽出し、再生成候補リストを出力する。

============================================================
使い方
============================================================
  # 全件表示
  python3 check_tts_diff.py

  # 差分のみ表示
  python3 check_tts_diff.py --diff-only

  # 再生成候補の slug を改行区切りで（パイプ用）
  python3 check_tts_diff.py --slugs-only > to_regenerate.txt
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import basay_text  # v3

SITE_ROOT = SCRIPT_DIR.parent
MANIFEST = SCRIPT_DIR / "audio_manifest.tsv"
DAILY_JSON = SITE_ROOT / "data" / "daily.json"
AUDIO_ROOT = SITE_ROOT / "education" / "phrasebook" / "audio"
IPAY_DIR = AUDIO_ROOT / "ipay"
HOKKIEN_DIR = AUDIO_ROOT / "hokkien"


# ─────────────────── v2 (旧ルール) を再現 ───────────────────
V2_VOWELS = set("aeiouəɨAEIOUƏ")
V2_FINAL_SUFFIXES = ("ku", "su", "an", "ay", "ai", "ik", "it", "is")
V2_PARTICLES = {"u", "ta", "a", "nu"}
V2_TRAIL_PUNCT_RE = re.compile(r"[^A-Za-zəɨŋŊ'’ʔ]+$")


def _v2_bare_lower(token):
    return V2_TRAIL_PUNCT_RE.sub("", token).lower()


def _v2_apply_consonant_colon(token):
    for i, ch in enumerate(token):
        if ch in V2_VOWELS:
            if i == 0:
                return token
            if token[i - 1] == ":":
                return token
            return token[:i] + ":" + token[i:]
    return token


def _v2_wants_trailing_comma(token):
    bare = _v2_bare_lower(token)
    if not bare:
        return False
    if bare in V2_PARTICLES:
        return True
    for suf in V2_FINAL_SUFFIXES:
        if bare.endswith(suf):
            return True
    return False


def v2_tts(display: str) -> str:
    if not display or not display.strip():
        return ""
    tokens = display.split()
    n = len(tokens)
    out = []
    for i, tok in enumerate(tokens):
        wants_comma = _v2_wants_trailing_comma(tok)
        new_tok = tok.replace("-", ":")
        new_tok = _v2_apply_consonant_colon(new_tok)
        if wants_comma and i < n - 1 and not new_tok.endswith(","):
            new_tok = new_tok + ","
        out.append(new_tok)
    return " ".join(out)


# ─────────────────── エントリ収集 ───────────────────
def collect_entries():
    """(source, display, manual_slug) のリスト。manual_slug は明示指定がなければ ''。"""
    seen_displays = set()
    entries = []

    if MANIFEST.exists():
        with MANIFEST.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.rstrip("\n")
                if not ln or ln.startswith("#"):
                    continue
                parts = ln.split("\t")
                if len(parts) < 2:
                    continue
                display = parts[0].strip()
                manual_slug = parts[1].strip()
                if display in seen_displays:
                    continue
                seen_displays.add(display)
                entries.append(("manifest", display, manual_slug))

    if DAILY_JSON.exists():
        with DAILY_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            display = (entry.get("word") or "").strip()
            manual_slug = (entry.get("slug") or "").strip()
            if not display or display in seen_displays:
                continue
            seen_displays.add(display)
            entries.append((f"daily:{key}", display, manual_slug))

    return entries


def wav_status(slug: str) -> str:
    ipay = (IPAY_DIR / f"{slug}.wav").exists()
    hokk = (HOKKIEN_DIR / f"{slug}.wav").exists()
    if ipay and hokk:
        return "✓"
    if ipay or hokk:
        return "△"  # どちらか欠
    return "✗"


# ─────────────────── メイン ───────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff-only", action="store_true",
                    help="v2 と v3 の TTS が異なるエントリのみ表示")
    ap.add_argument("--slugs-only", action="store_true",
                    help="差分のある slug を改行区切りで出力（パイプ用）")
    args = ap.parse_args()

    entries = collect_entries()
    rows = []
    for source, display, manual_slug in entries:
        d = basay_text.derive(display, manual_slug or None, None)
        v2 = v2_tts(display)
        v3 = d["tts"]
        slug = d["slug"]
        diff = (v2 != v3)
        rows.append({
            "source": source,
            "display": display,
            "slug": slug,
            "v2": v2,
            "v3": v3,
            "diff": diff,
            "wav": wav_status(slug),
        })

    if args.slugs_only:
        for r in rows:
            if r["diff"] and r["wav"] != "✗":
                print(r["slug"])
        return 0

    target = [r for r in rows if r["diff"]] if args.diff_only else rows

    print(f"total: {len(rows)}    diff: {sum(1 for r in rows if r['diff'])}    "
          f"with wav (full): {sum(1 for r in rows if r['wav'] == '✓')}")
    print("=" * 100)
    for r in target:
        marker = "△ 差分" if r["diff"] else "  同一"
        print(f"[{r['wav']}] {marker}  {r['source']}")
        print(f"     display: {r['display']}")
        print(f"     slug:    {r['slug']}")
        if r["diff"]:
            print(f"     v2 →     {r['v2']}")
            print(f"     v3 →     {r['v3']}")
        else:
            print(f"     tts:     {r['v3']}")
        print()

    print("─" * 100)
    diff_with_wav = [r for r in rows if r["diff"] and r["wav"] != "✗"]
    print(f"再生成候補（差分あり × wav 存在）: {len(diff_with_wav)} 件")
    for r in diff_with_wav:
        print(f"  {r['slug']:<40} {r['display']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
