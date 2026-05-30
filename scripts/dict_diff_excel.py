#!/usr/bin/env python3
"""
dict_diff_excel.py
==================
Excel master (basay_dictionary.xlsm) vs current data/dictionary.json:
report differences per entry and per field, in a human-readable form.

Usage:
  python3 scripts/dict_diff_excel.py
  python3 scripts/dict_diff_excel.py --summary
  python3 scripts/dict_diff_excel.py --id 0417 0419
  python3 scripts/dict_diff_excel.py --field category zh
  python3 scripts/dict_diff_excel.py --no-color
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import dict_excel_to_json as dx   # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
SITE_JSON = REPO_ROOT / "data" / "dictionary.json"

FIELDS = ("basay", "category", "zh", "ja", "en", "source", "original", "remark")


class C:
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

    @classmethod
    def disable(cls):
        for k in list(cls.__dict__):
            v = getattr(cls, k)
            if isinstance(v, str) and not k.startswith("_"):
                setattr(cls, k, "")


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return f"{C.DIM}(empty){C.RESET}"
    if isinstance(value, list):
        if not value:
            return f"{C.DIM}(empty list){C.RESET}"
        return " | ".join(str(v) for v in value)
    return str(value)


def load_current_json() -> dict[str, dict]:
    if not SITE_JSON.is_file():
        sys.exit(f"ERROR: {SITE_JSON} not found. Run dict_excel_to_json.py first.")
    with SITE_JSON.open(encoding="utf-8") as f:
        return {e["id"]: e for e in json.load(f)}


def load_excel() -> dict[str, dict]:
    entries, _ = dx.read_workbook(dx.DEFAULT_INPUT)
    return {e["id"]: e for e in entries}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--summary", action="store_true",
                   help="show only the summary counts")
    p.add_argument("--id", nargs="+", default=None,
                   help="filter to these IDs only (zero-padded auto, e.g. --id 0417 0419)")
    p.add_argument("--field", nargs="+", default=None,
                   help=f"compare only these fields. choices: {', '.join(FIELDS)}")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = p.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.disable()

    target_fields = tuple(args.field) if args.field else FIELDS
    invalid = set(target_fields) - set(FIELDS)
    if invalid:
        sys.exit(f"ERROR: unknown field(s): {sorted(invalid)}")

    target_ids = {x.zfill(4) for x in args.id} if args.id else None

    print(f"Reading current JSON: {SITE_JSON}")
    current = load_current_json()
    print(f"Reading Excel master: {dx.DEFAULT_INPUT}")
    new = load_excel()

    current_ids = set(current.keys())
    new_ids = set(new.keys())

    added   = sorted(new_ids - current_ids)
    removed = sorted(current_ids - new_ids)
    common  = sorted(current_ids & new_ids)

    modified: list[tuple[str, list[tuple[str, Any, Any]]]] = []
    for eid in common:
        if target_ids and eid not in target_ids:
            continue
        diffs = []
        for f in target_fields:
            old_v = current[eid].get(f)
            new_v = new[eid].get(f)
            old_norm = old_v if old_v else ([] if isinstance(old_v, list) else "")
            new_norm = new_v if new_v else ([] if isinstance(new_v, list) else "")
            if old_norm != new_norm:
                diffs.append((f, old_v, new_v))
        if diffs:
            modified.append((eid, diffs))

    if not args.summary:
        if modified:
            print()
            print(f"{C.BOLD}=== Modified entries ({len(modified)}) ==={C.RESET}")
            for eid, diffs in modified:
                basay = new[eid].get("basay", "?")
                print(f"\n{C.CYAN}{C.BOLD}ID={eid}{C.RESET}  basay={basay!r}")
                for field, old_v, new_v in diffs:
                    print(f"  {C.YELLOW}{field:10}{C.RESET}: "
                          f"{C.RED}{_fmt(old_v)}{C.RESET} → "
                          f"{C.GREEN}{_fmt(new_v)}{C.RESET}")

        if added and not target_ids:
            print()
            print(f"{C.BOLD}=== Added entries ({len(added)}) ==={C.RESET}")
            for eid in added[:50]:
                print(f"  {C.GREEN}+ ID={eid}{C.RESET}  basay={new[eid].get('basay','?')!r}")
            if len(added) > 50:
                print(f"  ... and {len(added) - 50} more")

        if removed and not target_ids:
            print()
            print(f"{C.BOLD}=== Removed entries ({len(removed)}) ==={C.RESET}")
            for eid in removed[:50]:
                print(f"  {C.RED}- ID={eid}{C.RESET}  basay={current[eid].get('basay','?')!r}")
            if len(removed) > 50:
                print(f"  ... and {len(removed) - 50} more")

    print()
    print(f"{C.BOLD}--- Summary ---{C.RESET}")
    print(f"  current JSON entries : {len(current_ids)}")
    print(f"  Excel entries        : {len(new_ids)}")
    print(f"  modified             : {len(modified)}")
    if not target_ids:
        print(f"  added                : {len(added)}")
        print(f"  removed              : {len(removed)}")

    has_diff = bool(modified) or bool(added) or bool(removed)
    if not has_diff:
        print(f"\n  {C.GREEN}OK No differences. Excel and JSON are in sync.{C.RESET}")

    return 1 if has_diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
