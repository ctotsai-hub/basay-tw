---
title: Basay TTS
emoji: 🗣️
colorFrom: yellow
colorTo: blue
sdk: gradio
sdk_version: 6.14.0
python_version: '3.13'
app_file: app.py
pinned: false
short_description: '巴賽語語音工具 — 文字轉語音・聲音複製・語音轉文字'
---

# 巴賽語語音工具 — basay.tw

**巴賽語（Trobiawan方言）復興のための言語科技統合プラットフォーム**

[![Live Demo](https://img.shields.io/badge/🚀-Live_Demo-blue)](https://inkuei-basaytts.hf.space/)
[![basay.tw](https://img.shields.io/badge/🌐-basay.tw-green)](https://basay.tw/)
[![辭典](https://img.shields.io/badge/📖-辭典-orange)](https://basay.tw/dictionary/)

👉 **[デモを開く（inkuei-basaytts.hf.space）](https://inkuei-basaytts.hf.space/)**

---

## 概要

本 Space は **文字轉語音・聲音複製・語音轉文字** の 3 機能を統合した巴賽語語音ツールです。

巴賽語（Basay）は台湾北東部に住んでいたケタガラン族（Ketagalan）の言語で、現在は消滅危機状態にあります。本プロジェクトは 1936–1937 年に日本の言語学者**淺井惠倫**が録音した歴史音源を中核に、現代の音声合成・認識技術で巴賽語を復元します。

---

## 機能

### 文字轉語音（TTS）

eSpeak NG 音声合成エンジンをベースに、淺井音源の実測 F1/F2/F3 値で母音を調整した巴賽語専用 TTS です。

- **IPay（淺井音色）**：歴史音源を重視した発音モデル（`bsy`）
- **標準（Std）**：バランス型モデル（`bsystd`）
- 繁體中文・英語・巴賽語の混合入力に対応
- 推定自然度：約 78–83%

#### 正書法・音標対照表

| 正書法 | 音価（IPA） | 説明 |
|--------|------------|------|
| `n'`   | ŋ           | 軟口蓋鼻音 |
| `s'`   | ʃ           | 歯茎硬口蓋摩擦音 |
| `l'`   | ɭ           | そり舌側面音 |
| `z'`   | ɮ           | 側面摩擦音 |
| `o'`   | ə           | 中央母音 |

**入力例：**
```
pusal'um
kuman su baute
sjali 台北
```

### 聲音複製（VC）

ユーザー録音を IPay / Std の音色に変換する Voice Conversion 機能（開発中）。

### 語音轉文字（ASR）

Whisper small を巴賽語データでファインチューニングした専用モデルによる音声認識です。3,000 語以上の辞書と多段階後処理パイプラインで精度を向上させています（[BasayASR Space](https://huggingface.co/spaces/inkuei/BasayASR) と同一エンジン）。

---

## 音源・テキスト資料

| 資料 | 内容 |
|------|------|
| 淺井惠倫 1936–1937 年田野録音 | 主要一次音源（ノイズ処理済み） |
| 李壬癸《Texts of the Trobiawan Dialect of Basay》（2014） | 主要テキスト資料 |
| 土田滋《台灣・平埔族の言語資料の整理と分析》（1991） | 語彙・文法参考資料 |

母音の実測値は Praat で分析した淺井音源の平均 F1/F2/F3 値を使用しています（世界初の系統的試み）。

---

## 辭典データ

3,000 語以上の辞書データを JSON Lines 形式で管理しています（[`dictionary/entries/`](https://github.com/ctotsai-hub/basay-tw/tree/main/dictionary/entries)）。

各エントリに含まれる情報：
- 巴賽語（ローマ字正書法）
- IPA 音標
- 繁體中文・日本語・英語・台語訳
- IPay 音色の合成音声（`ipay`）
- 台語対照音声（`hokkien`）

---

## Word Rewrite Dictionary（TTS 発音辞書）

発音専用の書き換え規則を `data/word_rewrites.tsv` で管理しています。

```
# 書式：<原形>\t<読み>
vavan	vapvan
```

管理ツール：
```bash
python3 tools/word_rewrites.py list
python3 tools/word_rewrites.py set vavan vapvan
python3 tools/word_rewrites.py remove vavan
```

---

## ローカル実行

```bash
git clone https://huggingface.co/spaces/inkuei/basaytts
cd basaytts
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## 関連リンク

- [basay.tw](https://basay.tw/) — 巴賽語復興プラットフォーム
- [辭典検索](https://basay.tw/dictionary/)
- [BasayASR Space](https://huggingface.co/spaces/inkuei/BasayASR) — 語音轉文字 Space

---

## 引用

```bibtex
@misc{basay-tw,
  title  = {basay.tw — 巴賽語語音工具},
  author = {蔡永桂},
  year   = {2026},
  note   = {基於淺井惠倫1936–1937年錄音},
  url    = {https://basay.tw}
}
```

---

© 2026 basay.tw — CC BY-NC-SA 4.0
