#!/usr/bin/env python3
"""
collect_basay.py
================
サイト内 HTML から data-basay="..." を抽出し、
TEXT<TAB>SLUG 形式の audio_manifest.tsv を生成。

使い方:
    python3 collect_basay.py
    （スクリプトの 1 つ上のディレクトリをサイトルートとして処理）

slug 変換規則（JS の slug() と整合）:
    英数字以外を _ に置換 → 前後 _ 除去 → 小文字化
"""
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
OUT = os.path.join(SCRIPT_DIR, "audio_manifest.tsv")

TARGETS = [
    "index.html",
    "grammar/index.html",
    "education/index.html",
]

PAT = re.compile(r'''data-basay\s*=\s*(["'])([^"']+?)\1''')


def to_slug(text: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '_', text)
    return s.strip('_').lower()


def main() -> int:
    seen = {}
    order = []
    for rel in TARGETS:
        path = os.path.join(SITE_ROOT, rel)
        if not os.path.isfile(path):
            print(f"skip (missing): {rel}", file=sys.stderr)
            continue
        with open(path, encoding='utf-8') as f:
            html = f.read()
        for m in PAT.finditer(html):
            text = m.group(2).strip()
            slug = to_slug(text)
            if not slug:
                continue
            if re.fullmatch(r'[0-9_]+', slug):
                print(f"! skip numeric-only: {rel} → {text}", file=sys.stderr)
                continue
            if slug not in seen:
                seen[slug] = text
                order.append(slug)
                print(f"+ {rel}: {text}  → {slug}", file=sys.stderr)

    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write("# TEXT\tSLUG\n")
        for slug in order:
            f.write(f"{seen[slug]}\t{slug}\n")

    print(f"\nmanifest: {OUT}", file=sys.stderr)
    print(f"entries:  {len(order)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
