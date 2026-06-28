# Basay Whisper Fine-tuning ガイド

## 必要なもの
- Google アカウント（Colab 用）
- HuggingFace アカウント（モデル保存用）
- Google Drive に以下をアップロード済み:
  - `BasayASR/` フォルダ全体
  - `basay-tw/` フォルダ全体（音声ファイル入り）

---

## Step 1: データセット準備（Mac ローカルで実行）

```bash
cd ~/Documents/BasayASR
pip install datasets soundfile
python prepare_dataset.py
# → dataset/train.jsonl, val.jsonl, test.jsonl が生成される
```

---

## Step 2: Google Drive にアップロード

Finder で以下を Google Drive にコピー:
- `~/Documents/BasayASR/` → `マイドライブ/BasayASR/`
- `~/Downloads/basay-tw/` → `マイドライブ/basay-tw/`

---

## Step 3: Google Colab で fine-tuning

https://colab.research.google.com で新規ノートブックを作成し、以下を実行:

### セル 1: ドライブのマウント
```python
from google.colab import drive
drive.mount('/content/drive')
```

### セル 2: 依存ライブラリのインストール
```python
!pip install -q transformers datasets accelerate evaluate jiwer soundfile librosa
```

### セル 3: HuggingFace ログイン（モデル保存用）
```python
from huggingface_hub import notebook_login
notebook_login()
```

### セル 4: fine-tuning 実行
```python
%cd /content/drive/MyDrive/BasayASR
!python finetune_whisper.py \
    --audio-base /content/drive/MyDrive/basay-tw/basay-tw/dictionary/audio/ipay \
    --epochs 30 \
    --push-to-hub inkuei/whisper-small-basay
```

**所要時間の目安（Colab T4）:** 約 60〜90 分

---

## Step 4: HF Spaces の app.py を更新

fine-tuning 完了後、`app.py` のモデルを差し替える（別途対応）。

---

## トラブルシューティング

- **OOM (メモリ不足)**: `--batch-size 8` を追加
- **遅すぎる**: `--epochs 10` に短縮して動作確認
- **音声ファイルが見つからない**: `--audio-base` パスを確認
