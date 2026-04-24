#!/usr/bin/env bash
# ============================================================
# gen_audio.sh — 1 語（または 1 文）の Basay を
#                IPay (bsy+f1) と 台語適合 (bsystd) で合成
# ------------------------------------------------------------
# 使い方:
#   ./gen_audio.sh "tsu" tsu
#   ./gen_audio.sh "m-ali ta vutsusa" m_ali_ta_vutsusa
#
# 引数:
#   $1  読み上げテキスト（クォート推奨）
#   $2  出力 wav のファイル名（拡張子なし／slug）
#
# 出力:
#   <SITE_ROOT>/education/phrasebook/audio/ipay/<slug>.wav
#   <SITE_ROOT>/education/phrasebook/audio/hokkien/<slug>.wav
#
# 必須:
#   - espeak-ng がインストール済み
#   - bsy / bsystd の音声定義が eSpeak-NG に登録済み
# ============================================================
set -euo pipefail

# ───── サイトルート（スクリプトの 1 つ上のディレクトリ）─────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AUDIO_ROOT="$SITE_ROOT/education/phrasebook/audio"
IPAY_DIR="$AUDIO_ROOT/ipay"
HOKKIEN_DIR="$AUDIO_ROOT/hokkien"

# ───── 音声定義（必要に応じて編集してください）─────
IPAY_VOICE="${IPAY_VOICE:-bsy+f1}"
HOKKIEN_VOICE="${HOKKIEN_VOICE:-bsystd}"

# ───── 引数チェック ─────
if [ "$#" -lt 2 ]; then
  echo "Usage: $0 \"<TEXT>\" <slug>" >&2
  echo "Example: $0 \"tsu\" tsu" >&2
  exit 1
fi

TEXT="$1"
SLUG="$2"

# slug の安全チェック（英数字 _ - のみ許容）
if ! [[ "$SLUG" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Error: slug must contain only A-Z a-z 0-9 _ -. Got: $SLUG" >&2
  exit 2
fi

# ───── espeak-ng の存在チェック ─────
if ! command -v espeak-ng >/dev/null 2>&1; then
  echo "Error: espeak-ng not found. Install with:" >&2
  echo "  sudo apt install espeak-ng   # Debian/Ubuntu" >&2
  exit 3
fi

# ───── 出力先ディレクトリ作成 ─────
mkdir -p "$IPAY_DIR" "$HOKKIEN_DIR"

IPAY_WAV="$IPAY_DIR/$SLUG.wav"
HOKKIEN_WAV="$HOKKIEN_DIR/$SLUG.wav"

# ───── 生成 ─────
echo "→ [IPay:$IPAY_VOICE]    \"$TEXT\" → $IPAY_WAV"
espeak-ng -v "$IPAY_VOICE" "$TEXT" -w "$IPAY_WAV"

echo "→ [台語:$HOKKIEN_VOICE] \"$TEXT\" → $HOKKIEN_WAV"
espeak-ng -v "$HOKKIEN_VOICE" "$TEXT" -w "$HOKKIEN_WAV"

echo "✓ done: $SLUG"
