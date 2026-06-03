#!/usr/bin/env python3
"""
remove_obsolete_audio.py
========================
Remove MP3 files under dictionary/audio/ that are no longer referenced
in data/dictionary.json, then commit and push.

Usage:
  python3 scripts/remove_obsolete_audio.py
  python3 scripts/remove_obsolete_audio.py --dry-run
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
SITE_JSON   = REPO_ROOT / "data" / "dictionary.json"
AUDIO_ROOT  = REPO_ROOT / "dictionary" / "audio"
VARIANTS    = ("ipay", "hokkien")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be removed without making any changes")
    args = ap.parse_args()

    if not SITE_JSON.is_file():
        sys.exit(f"ERROR: {SITE_JSON} not found. Run dict_excel_to_json.py first.")

    with SITE_JSON.open(encoding="utf-8") as f:
        data = json.load(f)

    valid_slugs = {
        e["audio"]["slug"]
        for e in data
        if "audio" in e and "slug" in e["audio"]
    }
    print(f"Valid slugs in dictionary.json: {len(valid_slugs)}")

    to_remove: list[Path] = []
    for variant in VARIANTS:
        variant_dir = AUDIO_ROOT / variant
        if not variant_dir.is_dir():
            continue
        for mp3 in variant_dir.rglob("*.mp3"):
            if mp3.stem not in valid_slugs:
                to_remove.append(mp3)

    if not to_remove:
        print("No obsolete files found.")
        return 0

    print(f"{'Would remove' if args.dry_run else 'Removing'} {len(to_remove)} file(s):")
    for p in sorted(to_remove):
        rel = p.relative_to(REPO_ROOT)
        print(f"  {rel}")

    if args.dry_run:
        return 0

    # git rm (paths relative to repo root)
    rel_paths = [str(p.relative_to(REPO_ROOT)) for p in sorted(to_remove)]
    subprocess.run(["git", "-C", str(REPO_ROOT), "rm"] + rel_paths, check=True)
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit", "-m", "Remove obsolete audio files"],
        check=True,
    )
    subprocess.run(["git", "-C", str(REPO_ROOT), "push"], check=True)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
