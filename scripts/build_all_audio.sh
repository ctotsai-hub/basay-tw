#!/usr/bin/env bash
# ============================================================
# build_all_audio.sh — manifest に基づき全 Basay 語の
#                      IPay / 台語 音源を一括生成
# ------------------------------------------------------------
# 使い方:
#   ./collect_basay.sh          # まず manifest を作成
#   ./build_all_audio.sh        # 全件生成（未生成のものだけ）
#   ./build_all_audio.sh -f     # 既存も上書き再生成
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$SCRIPT_DIR/audio_manifest.tsv"
AUDIO_ROOT="$SITE_ROOT/education/phrasebook/audio"

FORCE=0
if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--force" ]; then
  FORCE=1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "Error: $MANIFEST が存在しません。先に collect_basay.sh を実行してください。" >&2
  exit 1
fi

total=0
made=0
skipped=0
failed=0

while IFS=$'\t' read -r TEXT SLUG; do
  # コメント・空行スキップ
  [[ "$TEXT" =~ ^# ]] && continue
  [[ -z "$TEXT" ]] && continue
  total=$((total + 1))

  ipay_wav="$AUDIO_ROOT/ipay/$SLUG.wav"
  hokkien_wav="$AUDIO_ROOT/hokkien/$SLUG.wav"

  if [ "$FORCE" -eq 0 ] && [ -f "$ipay_wav" ] && [ -f "$hokkien_wav" ]; then
    skipped=$((skipped + 1))
    continue
  fi

  echo "[$total] $SLUG ← \"$TEXT\""
  if bash "$SCRIPT_DIR/gen_audio.sh" "$TEXT" "$SLUG"; then
    made=$((made + 1))
  else
    failed=$((failed + 1))
    echo "  ✗ failed: $SLUG" >&2
  fi
done < "$MANIFEST"

echo
echo "─────────────────────────────────"
echo "total:   $total"
echo "made:    $made"
echo "skipped: $skipped  (既存のためスキップ)"
echo "failed:  $failed"
echo "─────────────────────────────────"
[ "$failed" -eq 0 ]
