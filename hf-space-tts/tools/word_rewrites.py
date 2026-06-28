#!/usr/bin/env python3
"""Manage Basay TTS word rewrite dictionary.

Usage:
  python3 tools/word_rewrites.py list
  python3 tools/word_rewrites.py set vavan vapvan
  python3 tools/word_rewrites.py remove vavan
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = ROOT / "data" / "word_rewrites.tsv"
HEADER = [
    "# Basay TTS word rewrite dictionary.",
    "# Format: source<TAB>target",
    "# The source form is matched case-insensitively; slug/display keep the original input.",
]


def read_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    if not DICT_PATH.exists():
        return entries
    for line_no, raw in enumerate(DICT_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            source, target = line.split("\t", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise SystemExit(f"{DICT_PATH}:{line_no}: expected SOURCE<TAB>TARGET")
            source, target = parts
        source = source.strip().lower()
        target = target.strip()
        if not source or not target:
            raise SystemExit(f"{DICT_PATH}:{line_no}: source and target must be non-empty")
        entries[source] = target
    return entries


def write_entries(entries: dict[str, str]) -> None:
    DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = HEADER + [f"{source}\t{target}" for source, target in sorted(entries.items())]
    DICT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0

    command = argv[1]
    entries = read_entries()

    if command == "list":
        for source, target in sorted(entries.items()):
            print(f"{source}\t{target}")
        return 0

    if command == "set":
        if len(argv) != 4:
            raise SystemExit("Usage: python3 tools/word_rewrites.py set SOURCE TARGET")
        source = argv[2].strip().lower()
        target = argv[3].strip()
        if not source or not target:
            raise SystemExit("source and target must be non-empty")
        entries[source] = target
        write_entries(entries)
        print(f"set {source} -> {target}")
        return 0

    if command == "remove":
        if len(argv) != 3:
            raise SystemExit("Usage: python3 tools/word_rewrites.py remove SOURCE")
        source = argv[2].strip().lower()
        if source not in entries:
            raise SystemExit(f"{source} is not in {DICT_PATH}")
        del entries[source]
        write_entries(entries)
        print(f"removed {source}")
        return 0

    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
