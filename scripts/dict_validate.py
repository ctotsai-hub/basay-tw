#!/usr/bin/env python3
"""
dict_validate.py
================
Validate the consistency of the dictionary data.

Checks:
  - All required fields present (id, basay, category)
  - At least one gloss (zh OR ja OR en) per entry
  - No duplicate ids
  - Categories appear in dictionary/categories.json (warn otherwise)
  - Source codes (B/T/M/S/V) match the known set
  - slug collisions: distinct basay forms that derive the same audio slug
    (homograph entries that share basay are OK; this catches DIFFERENT
     basay strings collapsing to the same MP3 filename)

USAGE
-----
  python scripts/dict_validate.py
  python scripts/dict_validate.py --source data/dictionary.json
  python scripts/dict_validate.py --strict   # exit 1 on warnings too
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import basay_text  # type: ignore
    _HAS_BASAY_TEXT = True
except Exception:
    _HAS_BASAY_TEXT = False

REPO_ROOT       = SCRIPT_DIR.parent
ENTRIES_DIR     = REPO_ROOT / "dictionary" / "entries"
CATEGORIES_JSON = REPO_ROOT / "dictionary" / "categories.json"
SITE_JSON       = REPO_ROOT / "data" / "dictionary.json"

KNOWN_SOURCES = {"B", "T", "M", "S", "V", ""}


def _derive_slug(basay: str) -> str:
    primary = (basay or "").split("|")[0].strip()
    if not primary:
        return ""
    if _HAS_BASAY_TEXT:
        try:
            return basay_text.derive(primary)["slug"]
        except Exception:
            pass
    import re
    return re.sub(r"[^a-z0-9]+", "_", primary.lower()).strip("_")


def load_entries(source: Path) -> list[dict[str, Any]]:
    if source.is_dir():
        all_entries: list[dict[str, Any]] = []
        for p in sorted(source.glob("*.json")):
            if p.name == "_index.json":
                continue
            with p.open(encoding="utf-8") as f:
                all_entries.extend(json.load(f))
        return all_entries
    elif source.is_file():
        with source.open(encoding="utf-8") as f:
            return json.load(f)
    else:
        sys.exit(f"ERROR: source not found: {source}")


def load_categories() -> set[str]:
    if not CATEGORIES_JSON.is_file():
        return set()
    with CATEGORIES_JSON.open(encoding="utf-8") as f:
        return set(json.load(f).keys())


def validate(entries: list[dict[str, Any]], known_categories: set[str]
             ) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    seen_ids: dict[str, int] = {}
    slug_to_basay: dict[str, set[str]] = defaultdict(set)

    for i, e in enumerate(entries, start=1):
        eid    = (e.get("id") or "").strip()
        basay  = (e.get("basay") or "").strip()
        cat    = (e.get("category") or "").strip()
        source = (e.get("source") or "").strip()
        zh     = e.get("zh") or []
        ja     = e.get("ja") or []
        en     = e.get("en") or []

        # Required fields.
        if not eid:
            errors.append(f"#{i}: missing id")
        if not basay:
            errors.append(f"#{i} (id={eid!r}): missing basay")
        if not cat:
            warnings.append(f"#{i} (id={eid!r}, basay={basay!r}): empty category")

        # Gloss presence.
        if not (zh or ja or en):
            warnings.append(
                f"#{i} (id={eid!r}, basay={basay!r}): no gloss in zh/ja/en"
            )

        # Duplicate ids.
        if eid:
            if eid in seen_ids:
                errors.append(f"duplicate id {eid!r} at #{i} "
                              f"(first at #{seen_ids[eid]})")
            else:
                seen_ids[eid] = i

        # Category exists in categories.json.
        if cat and known_categories and cat not in known_categories:
            warnings.append(
                f"#{i} (id={eid!r}, basay={basay!r}): unknown category {cat!r}"
            )

        # Source code.
        if source and source not in KNOWN_SOURCES:
            warnings.append(
                f"#{i} (id={eid!r}, basay={basay!r}): "
                f"unknown source code {source!r} (expected one of {sorted(KNOWN_SOURCES)})"
            )

        # Slug collision tracking.
        if basay:
            slug = _derive_slug(basay)
            if slug:
                slug_to_basay[slug].add(basay)

    # Report slug collisions: same slug, different basay strings.
    collisions = {s: bs for s, bs in slug_to_basay.items() if len(bs) > 1}
    for slug, basays in collisions.items():
        warnings.append(
            f"slug collision {slug!r}: distinct basay forms {sorted(basays)!r} "
            "would share the same MP3 file"
        )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path,
                        help=f"entries dir or merged JSON. "
                             f"Default: {ENTRIES_DIR} if present, else {SITE_JSON}")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on warnings as well as errors")
    args = parser.parse_args()

    source = args.source or (ENTRIES_DIR if ENTRIES_DIR.is_dir() else SITE_JSON)
    print(f"Validating {source} ...")
    entries = load_entries(source)
    print(f"  {len(entries)} entries loaded")

    known = load_categories()
    if known:
        print(f"  {len(known)} known categories loaded")
    else:
        print(f"  (no categories.json found; category check skipped)")

    errors, warnings = validate(entries, known)

    for w in warnings:
        print(f"  ! warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"  X ERROR:  {e}", file=sys.stderr)

    print()
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s)")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
