---
title: Basay ASR
emoji: 🎙️
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "6.19.0"
python_version: "3.13"
app_file: app.py
pinned: false
short_description: 巴賽語語音轉文字 — Whisper fine-tuned + 3,000 詞辭典
---

# 巴賽語語音轉文字 — BasayASR

[![Live Demo](https://img.shields.io/badge/🚀-Live_Demo-blue)](https://inkuei-basaytts.hf.space/)
[![Basay TTS](https://img.shields.io/badge/🗣️-文字轉語音-orange)](https://inkuei-basaytts.hf.space/)
[![basay.tw](https://img.shields.io/badge/🌐-basay.tw-green)](https://basay.tw/)

巴賽語（Basay / Ketagalan）の音声認識システムです。Whisper を巴賽語音声データでファインチューニングしたモデルと、3,000 語以上の辞書・音韻補正パイプラインを組み合わせた転写ツールです。

本 Space は **[巴賽語語音工具](https://inkuei-basaytts.hf.space/)** の「語音轉文字」タブに統合されています。

---

## 言語モード

| モード | 内容 |
|--------|------|
| **巴賽語 v1** | Whisper small を巴賽語 TTS データ（epoch 5）でファインチューニングした専用モデル |
| **多語言** | 繁體中文・English・巴賽語混合音声に対応。zh + fine-tuned の 2 パス方式 |

---

## 転写後処理パイプライン（巴賽語モード）

音声 → Whisper fine-tuned → 以下の順で補正：

1. **UI 補正ルール**（進階設定で編集可）— トークン完全一致 / フレーズ / プレフィックス / サフィックス / インフィックス
2. **音素補正** — `q ↔ k`・`b → v`・`j → y`（語頭）など fine-tuned モデル固有の系統誤認を修正
3. **1sg エンクリティック分離** — `n'u` 末尾語（`n'` = `ŋ`）から `u` を分離（例：`kumokon'u` → `kumokon' u`）
4. **形態素再結合** — 過分割トークンを辞書照合で再結合
5. **語境界回復** — 融合トークンを最大マッチング分割
6. **辞書スナップ**（cutoff 0.88）— 最近傍辞書エントリに補正
7. **辞書ルックアップ** — 繁體中文・日本語・英語で語義表示
8. **音節境界解析** — CV / CVC 形式で分割表示

---

## 巴賽語正書法（参考）

| 表記 | 音価 |
|------|------|
| `n'` | `ŋ`（軟口蓋鼻音）— アポストロフィは削除不可 |
| `'` | 声門閉鎖音（形態素境界） |
| 語末 `-u` | 1sg 行為者エンクリティック |

---

## 進階設定（⚙ ボタン）

メインページ下部の「⚙ 進階設定」から以下を設定できます：

- **巴賽語補正ルール** — 誤認パターンを手動定義・保存
- **言語（完整列表）** — fine-tuned v2 / MMS (ami) / 標準 Whisper 各モードを選択
- **提示詞** — 辞書自動生成プロンプトを上書き
- **降噪** — スペクトル減算ノイズ除去（歴史音源向け）
- **時間戳記分段** — セグメントの開始・終了時刻表示
- **音節邊界解析** — 単語ごとの音節分割表示

---

## モデル

| ディレクトリ | 内容 |
|---|---|
| `whisper-basay-finetuned/` | Whisper small、epoch 5（WER 25.6%） |
| `whisper-basay-finetuned-v2/` | Whisper small、epoch 25 |

ベースモデル：`openai/whisper-small`  
フレームワーク：`faster-whisper` + `transformers`

---

## データファイル

```
dictionary/
  basay_dict.jsonl          # 3,000+ 語（巴賽語・繁體中文・日本語・英語・台語）
config/
  rules.txt                 # 音韻変換規則（mi/ami 向け）
  alts.txt                  # 音素候補表
  basay_corrections.txt     # fine-tuned モデル向け補正ルール
syllable/
  basay_syllable_inventory.md  # 有効音節目録（CV / CVC / CVGV 等）
```

---

## ローカル実行

```bash
git clone https://huggingface.co/spaces/inkuei/BasayASR
cd BasayASR
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

`whisper-basay-finetuned/` にファインチューニング済みモデルを配置してください（Git LFS で管理）。

---

## 関連リンク

- [巴賽語語音工具（統合 UI）](https://inkuei-basaytts.hf.space/) — 文字轉語音 · 聲音複製 · 語音轉文字
- [basay.tw](https://basay.tw/) — 辭典・語言復興プラットフォーム
- [BasayTTS Space](https://huggingface.co/spaces/inkuei/basaytts)

---

© 2026 basay.tw — CC BY-NC-SA 4.0
