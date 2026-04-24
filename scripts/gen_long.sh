#!/usr/bin/env bash
# ============================================================
# gen_long.sh — 長文 Basay の音声生成（プロソディー自動挿入つき）
# ------------------------------------------------------------
# 使い方:
#   ./gen_long.sh "Basay の長文" slug
#   ./gen_long.sh -n "Basay の長文"      # slug を自動生成
#   ./gen_long.sh --dry "text"           # プロソディー結果だけ表示、wav は作らない
#
# 動作:
#   1. 入力テキストを prosody.py に渡し、',' '.' を自動挿入
#   2. 結果を表示（目視チェック用）
#   3. gen_audio.sh を呼んで IPay / 台語 両方の wav を生成
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROSODY="$SCRIPT_DIR/prosody.py"
GEN_AUDIO="$SCRIPT_DIR/gen_audio.sh"

dry_run=0
auto_slug=0

# オプション処理
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry) dry_run=1; shift ;;
        -n|--auto-slug) auto_slug=1; shift ;;
        -h|--help)
            cat <<EOF
使い方:
  $0 "Basay text" slug        ... 指定 slug で wav 生成
  $0 -n "Basay text"          ... slug を自動生成
  $0 --dry "Basay text"       ... プロソディー結果だけ表示

必須:
  prosody.py, gen_audio.sh が同じディレクトリにあること
EOF
            exit 0 ;;
        *) break ;;
    esac
done

if [[ $# -lt 1 ]]; then
    echo "Error: text 引数がありません。--help 参照。" >&2
    exit 1
fi

TEXT="$1"

# slug 決定
if [[ $auto_slug -eq 1 || $# -lt 2 ]]; then
    # 英数字以外を _ に → 前後 _ 除去 → 小文字化
    SLUG="$(printf '%s' "$TEXT" | python3 -c '
import sys, re
t = sys.stdin.read().strip()
print(re.sub(r"[^A-Za-z0-9]+","_", t).strip("_").lower())
')"
else
    SLUG="$2"
fi

if [[ -z "$SLUG" ]]; then
    echo "Error: slug が空です。" >&2
    exit 1
fi

# プロソディー処理
PROSODIZED="$(python3 "$PROSODY" "$TEXT")"

echo "───────────────────────────────────────────────"
echo "  入力 : $TEXT"
echo "  整形 : $PROSODIZED"
echo "  slug : $SLUG"
echo "───────────────────────────────────────────────"

if [[ $dry_run -eq 1 ]]; then
    echo "(--dry: 音声生成はスキップ)"
    exit 0
fi

# gen_audio.sh に渡す
"$GEN_AUDIO" "$PROSODIZED" "$SLUG"
