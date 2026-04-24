#!/usr/bin/env bash
# ============================================================
# collect_basay.sh — collect_basay.py のラッパー
# ------------------------------------------------------------
# サイト内 HTML から data-basay="..." を抽出し
# TEXT<TAB>SLUG 形式の audio_manifest.tsv を生成します。
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/collect_basay.py"
