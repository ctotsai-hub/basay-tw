**巴賽語（Trobiawan方言）復興のための言語科技專案**

## 專案簡介

**basay.tw** 是致力於復興台灣北部**巴賽語（Basay）**——特別是Trobiawan方言——的開源語言復興平台。


# 辭典資料 / Dictionary Data

- 李壬癸教授《**Texts of the Trobiawan Dialect of Basay**》（2014）
- 土田 滋教授《**台灣・平埔族の言語資料の整理と分析**》（1991）
本專案主要以以上兩部重要著作及淺井惠倫音檔為基礎進行重建。

## ディレクトリ構成

```
dictionary/
├── source/                       ← ローカルのみ（.gitignore 除外）
│   └── basay_dictionary.xlsm     ← 編集用マスター（マクロ有効Excel）
├── entries/                      ← 自動生成：頭文字ごとに分割した JSON
│   ├── a.json … z.json           ← 21ファイル（実データ）
│   └── _index.json               ← id → 頭文字 のマッピング
├── audio/                        ← 自動生成：MP3（GitHub Pages から配信）
│   ├── ipay/<slug>.mp3           ← 巴賽語 TTS（voice: bsy+f1）
│   └── hokkien/<slug>.mp3        ← 台語 TTS（voice: bsystd）
├── categories.json               ← 自動生成：番号 → 全文ラベル
└── README.md                     ← このファイル

data/
├── dictionary.json               ← 自動生成：サイト配信用（マージ済み・1ファイル）
├── search-index.json             ← 自動生成：検索用の軽量インデックス
├── basay_dict.jsonl              ← 自動生成：AI研究者向け（1行1エントリ）
└── basay_dict.parquet            ← 自動生成：AI研究者向け（列指向・snappy圧縮）
```

## Excel 列構成

| 列名               | 必須 | JSON フィールド | 説明                                           |
|--------------------|------|-----------------|------------------------------------------------|
| `ID`               | ○    | `id`            | 整数。JSON では4桁ゼロパディング（`"0001"`）   |
| `basay`            | ○    | `basay`         | 巴賽語ローマ字。異形は `\|` 区切り            |
| `pos`（1つめ）     | ○    | `category`      | 意味カテゴリ。JSON には**先頭番号のみ**（容量節約）|
| `zh`               | △    | `zh`            | 中文訳。`\|` `、` `；` `改行` で複数値        |
| `ja`               | △    | `ja`            | 日本語訳。同上                                 |
| `en`               | △    | `en`            | 英語訳。同上                                   |
| `pos`（2つめ）     |      | `source`        | 出典コード `B/T/M/S/V`                         |
| `original_entry`   |      | `original`      | 原表記（IPA寄り、`ŋ` `ə` などを含む）         |
| `remark`           |      | `remark`        | 例文・補足（複数行可、改行は Alt+Enter）       |

△ = `zh`/`ja`/`en` のいずれか1つは必須

**出典コード（`source`）**：

- `B` = Basay
- `T` = Trobiawan
- `M` = Trobiawan-m
- `S` = Trobiawan-s
- `V` = 台語（Taiwanese）
- `PAN` = 南島祖語（Proto-Austronesian、再構形）

**正書法変換ルール**：`ŋ > n'`、`ʃ > s'`、`ɭ > l'`、`ɮ > z'`、`ə > o'`、`Dᵒ > z'`
（`conversion_rules` シートに記載。`basay` 列は変換後の正規形、`original_entry` は変換前の原表記）

## カテゴリの番号化

実データの 31 カテゴリは番号プレフィックスを持つ（`29情緒思維（精神性）` など）。
JSON には **番号のみ** を保存し、サイト表示時に `categories.json` から全文を引く：

```json
// dictionary/categories.json
{
  "01": "01數字計量",
  "02": "02代名詞、指示詞",
  ...
  "29": "29情緒思維（精神性）"
}
```

これで `dictionary.json` のサイズが約 60 KB（gzip 後 12 KB 弱）節約できる。

## AI研究者向けエクスポート

```
data/
├── basay_dict.jsonl     ← 全エントリ1行1JSON（研究・学習用）
└── basay_dict.parquet   ← Parquet形式（snappy圧縮、列指向）
```

**フラット化スキーマ**：

| フィールド       | 型                   | 説明                                      |
|-----------------|----------------------|-------------------------------------------|
| `id`            | str                  | 4桁ゼロパディング                          |
| `basay`         | str                  | 巴賽語ローマ字                             |
| `category`      | str                  | カテゴリ番号（"29" など）                  |
| `category_label`| str                  | カテゴリ全文（"29情緒思維（精神性）"）      |
| `zh` / `ja` / `en` | list[str] / str  | 訳語（JSONL: 配列、Parquet: `\|` 区切り）  |
| `source`        | str                  | B/T/M/S/V/PAN                             |
| `original`      | str                  | 原表記（IPA寄り）                          |
| `remark`        | str                  | 例文・補足                                 |
| `audio_slug`    | str                  | MP3ファイル名のstem                        |
| `audio_ipay`    | str                  | 巴賽語TTS音声パス（空文字＝未生成）         |
| `audio_hokkien` | str                  | 台語TTS音声パス（空文字＝未生成）           |

```bash
# 手動実行
python scripts/dict_export_research.py

# オプション
python scripts/dict_export_research.py --jsonl-only    # Parquet不要な場合
python scripts/dict_export_research.py --parquet-only
python scripts/dict_export_research.py --output-dir /path/to/out

# dict_excel_to_json.py 実行時に自動でエクスポートされる（抑制するには --no-export）
python scripts/dict_excel_to_json.py --no-export
```

依存：`pyarrow`（Parquet出力のみ）。`pip install pyarrow`

## ワークフロー

### 通常の編集（Excel → JSON → サイト配信）

```bash
# 1. dictionary/source/basay_dictionary.xlsm を編集
# 2. JSON 生成（＋自動でJSONL/Parquetエクスポート）
python scripts/dict_excel_to_json.py

# 3. 検証
python scripts/dict_validate.py

# 4. 音声追加（espeak-ng + ffmpeg のある環境で）
python scripts/dict_build_audio.py

# 5. コミット
git add dictionary/ data/
git commit -m "Update dictionary (N entries, audio for M new)"
git push
```

### JSON → Excel に巻き戻す

他の人が PR で `entries/*.json` を直接編集した場合などに、Excel マスターを
最新状態に再生成：

```bash
python scripts/dict_json_to_excel.py
```

**注意**：`openpyxl` は VBA マクロを保持できないため、出力は `.xlsx` になります。
マクロを使っている場合は手動で `.xlsm` にして再ペースト。

### 音声を追加・更新する

MP3 は `dictionary/audio/{ipay,hokkien}/<slug>.mp3` に保存される。slug は
`basay` 表記から `basay_text.derive()` で自動派生（フレーズブックと同じ規則）。
**異形は `|` の前にある主形を採用**するので、`bolo | bolobolo` も `bolo` も
同じ `bolo.mp3` を共有する。

```bash
python scripts/dict_build_audio.py                # 未生成分だけ
python scripts/dict_build_audio.py --only ipay    # 一方の音声だけ
python scripts/dict_build_audio.py --force        # 全件再生成
python scripts/dict_build_audio.py --bitrate 48k  # 軽量化
python scripts/dict_build_audio.py --dry-run      # 何が生成されるか確認
```

生成後は `dict_excel_to_json.py` が自動で再実行され、`audio` フィールドが
JSON に反映される。

**サイズ目安**（GitHub 無料枠での配信想定）：

| 語数 | 1音声  | 2音声  |
|-----:|-------:|-------:|
| 2400 |  48 MB |  96 MB |
| 4000 |  80 MB | 160 MB |

依存：`espeak-ng`（巴賽語/台語ボイス設定済み）、`ffmpeg`。

## 検証

```bash
python scripts/dict_validate.py
```

確認項目：

- 必須フィールド（id, basay, category）の有無
- 重複 ID（エラー扱い）
- gloss（zh/ja/en）が1つも無いエントリ
- 未知のカテゴリ番号
- 未知の出典コード
- **slug 衝突**（異なる basay 文字列が同じ MP3 ファイル名に潰れるケース）

slug 衝突警告の見方：

```
slug collision 'bolo': distinct basay forms ['bolo', 'bolo | bolobolo']
```

- `'X', 'X | Y'` パターン → 主形が同じで意図通り（無視可）
- `'X', '-X'` パターン → クリティック（接尾辞）と独立形、別音声が望ましい
- `'Xy', 'XY'` パターン → 大小文字違い、データ修正が必要かもしれない
- 完全に違う綴り → データ修正が必要

## 設計メモ

- **id 採番方針**：単純連番（`0001` 〜 `9999`）。削除した id は再利用しない（履歴追跡のため）
- **頭文字バケット（Plan B）**：4桁IDなのでバケット内の追加・削除でも diff が安定
- **同形異義語（homograph）**：同じ basay の別 ID エントリは音声 MP3 を共有
- **異形（variants）**：`basay = "X | Y"` 形式は単一エントリ。音声は X（主形）の slug を使う

## 引用方式

本專案または資料を使用する場合は、以下のように引用してください：

```bibtex
@misc{basay-tw,
  title = {basay.tw — 凱達格蘭 · 巴賽語— 從記憶到再生},
  author = {蔡永桂},
  year = {2026},
  note = {基於淺井惠倫1936-1937年錄音},
  url = {https://basay.tw}
}