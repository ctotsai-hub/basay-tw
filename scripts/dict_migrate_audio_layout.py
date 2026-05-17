#!/usr/bin/env python3
"""
dict_migrate_audio_layout.py
============================
ONE-TIME migration: move existing MP3 files from the flat layout
    dictionary/audio/<variant>/<slug>.mp3
to letter subdirectories
    dictionary/audio/<variant>/<letter>/<slug>.mp3

Why: GitHub's web UI truncates directory listings at 1000 files.
With ~2120+ MP3s per variant, browsing is broken. The letter-bucket
layout keeps each directory well under the limit.

After migration:
  - dict_build_audio.py writes to the new layout going forward
  - dict_excel_to_json.py detect_audio looks in subfolders (with
    backward-compat fallback during migration)
  - Old flat-layout files in this repo get moved (this script)

USAGE
-----
  python scripts/dict_migrate_audio_layout.py              # dry-run by default
  python scripts/dict_migrate_audio_layout.py --apply      # actually move files
  python scripts/dict_migrate_audio_layout.py --variant ipay --apply

The script uses Path.rename (atomic on same filesystem). Idempotent:
re-running after migration moves 0 files.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parent.parent
AUDIO_ROOT = REPO_ROOT / "dictionary" / "audio"
VARIANTS   = ("ipay", "hokkien")


def slug_letter(slug: str) -> str:
    if slug:
        first = slug[0].lower()
        if "a" <= first <= "z":
            return first
    return "_misc"


def migrate(variant: str, apply: bool) -> tuple[int, int, Counter]:
    folder = AUDIO_ROOT / variant
    if not folder.is_dir():
        print(f"  (no folder: {folder})")
        return 0, 0, Counter()

    counts: Counter = Counter()
    moved = 0
    skipped = 0

    for mp3 in sorted(folder.glob("*.mp3")):
        # Only files directly in the flat folder, not already in a subfolder
        slug = mp3.stem
        letter = slug_letter(slug)
        target_dir = folder / letter
        target = target_dir / mp3.name

        if target.exists():
            print(f"  ! skip (target exists): {variant}/{letter}/{mp3.name}")
            skipped += 1
            continue

        counts[letter] += 1
        if apply:
            target_dir.mkdir(parents=True, exist_ok=True)
            mp3.rename(target)
            moved += 1
        else:
            print(f"  DRY  {variant}/{mp3.name}  ->  {variant}/{letter}/{mp3.name}")
            moved += 1   # planned count

    return moved, skipped, counts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="Actually move files. Without this flag, just report plan (dry run).")
    p.add_argument("--variant", choices=list(VARIANTS),
                   help="Only migrate this variant. Default: all variants.")
    args = p.parse_args()

    variants = [args.variant] if args.variant else list(VARIANTS)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode}  (audio root: {AUDIO_ROOT}) ===\n")

    total_moved = 0
    total_skipped = 0
    for v in variants:
        print(f"[{v}]")
        moved, skipped, counts = migrate(v, args.apply)
        if counts:
            print(f"  per-letter: " + ", ".join(f"{k}={c}" for k, c in
                                                sorted(counts.items())))
        print(f"  → {moved} {'moved' if args.apply else 'planned'}, {skipped} skipped\n")
        total_moved += moved
        total_skipped += skipped

    print(f"=== Total: {total_moved} {'moved' if args.apply else 'planned'}, "
          f"{total_skipped} skipped ===")
    if not args.apply:
        print("\n(Pass --apply to actually move files.)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Tolerate `| head` etc. closing stdout early.
        sys.stderr.close()
        raise SystemExit(0)
