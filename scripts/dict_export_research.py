#!/usr/bin/env python3
"""
dict_export_research.py
=======================
Export the Basay dictionary as a single JSONL and/or Parquet file for AI
researchers and downstream NLP use.

Source (read-only):
  data/dictionary.json          merged, sorted canonical list
  dictionary/categories.json    category number -> full label

Outputs:
  data/basay_dict.jsonl         one JSON object per line
  data/basay_dict.parquet       columnar, Parquet v2 (snappy-compressed)

Flat schema per entry
---------------------
  id              str        "0001"
  basay           str        "abal'"
  category        str        "29"
  category_label  str        "29情緒思維（精神性）"   (empty if unknown)
  zh              list[str]  Chinese glosses  (JSONL) / pipe-joined str (Parquet)
  ja              list[str]  Japanese glosses (JSONL) / pipe-joined str (Parquet)
  en              list[str]  English glosses  (JSONL) / pipe-joined str (Parquet)
  source          str        "B" / "T" / "M" / "S" / "V" / "PAN"
  original        str        original IPA-like notation
  remark          str        example sentences / notes
  audio_slug      str        slug used for mp3 filename  (empty if no audio)
  audio_ipay      str        "dictionary/audio/ipay/a/abalx.mp3"  (empty if absent)
  audio_hokkien   str        "dictionary/audio/hokkien/a/abalx.mp3"

Re-run safety
-------------
Outputs are overwritten on every run.  Run this script after dict_excel_to_json.py
(which regenerates data/dictionary.json) to keep exports in sync.

Typical workflow
----------------
  python scripts/dict_excel_to_json.py   # regenerate JSON from Excel
  python scripts/dict_export_research.py # export JSONL + Parquet

Options
-------
  --jsonl-only       skip Parquet output (no pyarrow needed)
  --parquet-only     skip JSONL output
  --output-dir DIR   write outputs here instead of data/
  --pipe-sep SEP     separator for multi-value fields in Parquet (default "|")
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent

DEFAULT_DICT_JSON   = REPO_ROOT / "data" / "dictionary.json"
DEFAULT_CATEGORIES  = REPO_ROOT / "dictionary" / "categories.json"
DEFAULT_OUTPUT_DIR  = REPO_ROOT / "data"

JSONL_FILENAME    = "basay_dict.jsonl"
PARQUET_FILENAME  = "basay_dict.parquet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def flatten_entry(entry: dict, categories: dict[str, str]) -> dict:
    """Return a flat dict suitable for both JSONL and Parquet rows."""
    cat = entry.get("category", "")
    audio = entry.get("audio") or {}

    return {
        "id":             entry.get("id", ""),
        "basay":          entry.get("basay", ""),
        "category":       cat,
        "category_label": categories.get(cat, ""),
        "zh":             entry.get("zh") or [],
        "ja":             entry.get("ja") or [],
        "en":             entry.get("en") or [],
        "source":         entry.get("source", ""),
        "original":       entry.get("original", ""),
        "remark":         entry.get("remark", ""),
        "audio_slug":     audio.get("slug", ""),
        "audio_ipay":     audio.get("ipay", ""),
        "audio_hokkien":  audio.get("hokkien", ""),
    }


# ---------------------------------------------------------------------------
# JSONL export
# ---------------------------------------------------------------------------

def export_jsonl(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  -> {out_path}  ({len(rows)} lines)")


# ---------------------------------------------------------------------------
# Parquet export
# ---------------------------------------------------------------------------

def export_parquet(rows: list[dict], out_path: Path, pipe_sep: str = "|") -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("ERROR: pyarrow is not installed.  Run:  pip install pyarrow",
              file=sys.stderr)
        sys.exit(1)

    # For Parquet, join list fields into pipe-separated strings.
    parquet_rows = []
    for row in rows:
        pr = dict(row)
        for field in ("zh", "ja", "en"):
            pr[field] = pipe_sep.join(pr[field]) if pr[field] else ""
        parquet_rows.append(pr)

    schema = pa.schema([
        ("id",             pa.string()),
        ("basay",          pa.string()),
        ("category",       pa.string()),
        ("category_label", pa.string()),
        ("zh",             pa.string()),
        ("ja",             pa.string()),
        ("en",             pa.string()),
        ("source",         pa.string()),
        ("original",       pa.string()),
        ("remark",         pa.string()),
        ("audio_slug",     pa.string()),
        ("audio_ipay",     pa.string()),
        ("audio_hokkien",  pa.string()),
    ])

    columns: dict[str, list] = {k: [] for k in schema.names}
    for pr in parquet_rows:
        for k in schema.names:
            columns[k].append(pr.get(k, ""))

    table = pa.table(columns, schema=schema)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="snappy")
    print(f"  -> {out_path}  ({len(parquet_rows)} rows, snappy-compressed)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input", "-i", type=Path, default=DEFAULT_DICT_JSON,
                    help="Path to data/dictionary.json (default: auto-detect)")
    ap.add_argument("--categories", "-c", type=Path, default=DEFAULT_CATEGORIES,
                    help="Path to dictionary/categories.json")
    ap.add_argument("--output-dir", "-o", type=Path, default=DEFAULT_OUTPUT_DIR,
                    help="Directory for output files (default: data/)")
    ap.add_argument("--jsonl-only",   action="store_true",
                    help="Only write JSONL, skip Parquet")
    ap.add_argument("--parquet-only", action="store_true",
                    help="Only write Parquet, skip JSONL")
    ap.add_argument("--pipe-sep", default="|",
                    help="Multi-value separator in Parquet string fields (default: '|')")
    args = ap.parse_args()

    # ---- load source data ----
    if not args.input.exists():
        sys.exit(f"ERROR: dictionary JSON not found: {args.input}\n"
                 "       Run dict_excel_to_json.py first.")
    print(f"Reading {args.input} ...")
    raw_entries: list[dict] = load_json(args.input)  # type: ignore
    print(f"  {len(raw_entries)} entries loaded")

    categories: dict[str, str] = {}
    if args.categories.exists():
        categories = load_json(args.categories)  # type: ignore
        print(f"  {len(categories)} categories loaded from {args.categories}")
    else:
        print(f"  (categories.json not found, category_label will be empty)",
              file=sys.stderr)

    # ---- flatten ----
    rows = [flatten_entry(e, categories) for e in raw_entries]

    audio_ipay_count    = sum(1 for r in rows if r["audio_ipay"])
    audio_hokkien_count = sum(1 for r in rows if r["audio_hokkien"])
    print(f"  audio_ipay:    {audio_ipay_count}/{len(rows)} entries")
    print(f"  audio_hokkien: {audio_hokkien_count}/{len(rows)} entries")

    # ---- export ----
    write_jsonl   = not args.parquet_only
    write_parquet = not args.jsonl_only

    if write_jsonl:
        export_jsonl(rows, args.output_dir / JSONL_FILENAME)

    if write_parquet:
        export_parquet(rows, args.output_dir / PARQUET_FILENAME, args.pipe_sep)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
