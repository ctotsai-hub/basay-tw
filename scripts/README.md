# 音聲生成スクリプト

eSpeak-NG を用いて basay.tw サイトの全 Basay 例文の音声ファイル（IPay / 台語）を生成するためのスクリプト群。

## 前提

- `espeak-ng` がインストール済み（`sudo apt install espeak-ng` / macOS は `brew install espeak-ng`）
- eSpeak-NG に `bsy`（IPay 歴史復元）と `bsystd`（台語適合・Lobanov）の音声定義が登録済み
- `python3`（collect_basay.py 用）

音声は以下に出力されます：

```
/education/phrasebook/audio/ipay/{slug}.wav
/education/phrasebook/audio/hokkien/{slug}.wav
```

phrasebook が参照しているのと同じパスで、文法・教育・首頁の全ページから共有されます。

## 含まれるファイル

| ファイル | 役割 |
|---|---|
| `gen_audio.sh` | 1 語を IPay と 台語 の 2 音源で生成（単体使用可） |
| `gen_long.sh` | 長文用ラッパー。`prosody.py` で句読点自動挿入 → `gen_audio.sh` |
| `prosody.py` | Basay 長文に `,` / `.` を自動挿入（eSpeak-NG TTS 用） |
| `collect_basay.py` | HTML から `data-basay="..."` 属性を抽出して manifest を生成 |
| `collect_basay.sh` | 上記 Python スクリプトの bash ラッパー |
| `build_all_audio.sh` | manifest を読んで全件を一括生成 |
| `audio_manifest.tsv` | 現時点の全 Basay 例文一覧（TEXT\tSLUG） |

## 使い方

### 1. 単体で 1 語生成

```bash
./gen_audio.sh "tsu" tsu
./gen_audio.sh "m-ali ta vutsusa" m_ali_ta_vutsusa
```

両方の声線で `.wav` が作られます。

### 2. サイト全件を一括生成

```bash
# （任意）最新の data-basay 属性で manifest を更新
./collect_basay.sh

# 全件生成（既存ファイルはスキップ）
./build_all_audio.sh

# 上書き再生成が必要なとき
./build_all_audio.sh -f
```

### 3. 音声を切り替えたい場合

環境変数でボイス指定を上書きできます：

```bash
IPAY_VOICE="bsy+f2" HOKKIEN_VOICE="bsystd+m1" ./gen_audio.sh "tsu" tsu
```

## manifest の更新

ページに新しい `data-basay="..."` を追加したら `collect_basay.sh` を再実行して manifest を更新し、`build_all_audio.sh` を回してください。`-f` を付けなければ既存の wav はスキップされます。

## 長文のプロソディー処理（`prosody.py` / `gen_long.sh`）

eSpeak-NG は自然な発話にするためテキスト中の `,` / `.` で区切りを付けます。
長文 Basay にこれを手で書き込むのは面倒なので、`prosody.py` が
Basay の文法規則（格標記・代名詞・アスペクト等）に基づいて自動挿入します。

### 単体でプロソディー処理だけ試す

```bash
python3 prosody.py "Pina i tia na zijan kuwarij-an-a ni qupa"
# → Pina i, tia, na, zijan kuwarij.an.a, ni, qupa

# stdin も可
echo "Azasa nu zanum-na" | python3 prosody.py

# 組み込みテストケース実行
python3 prosody.py --test
```

### 自動適用ルール（抜粋）

- **`.` （ピリオド）**
  - `-`（ハイフン）→ `.` に変換（音節境界）
  - 4 音節以上の単語に中間 `.` を挿入
- **`,` （カンマ）**
  - 格標記で始まるトークンの先頭 `-` は `,` に（例: `I-kuman-isu` → `I,kuman.isu`）
  - スタンドアロンの格標記（u, ta, i, s, na, nu, ni）の直後に `,`
  - リガーチャ `a` の直後に `,`
  - 代名詞接尾辞（-ik, -isu, -aku 等）やアスペクト（-a, -i, na）末尾に `,`

### 自動化しない部分（目視で調整）

- demonstrative の後の semantic pause
- 畳語（reduplication）分割
- 3 音節語の内部分割

出力を見ておかしい箇所だけ手で直してから `gen_audio.sh` に渡してください。

### 長文を一気に wav 化

```bash
# slug も自動生成してくれる
./gen_long.sh -n "Pina i tia na zijan kuwarij-an-a ni qupa"

# slug を明示
./gen_long.sh "Azasa nu zanum-na" azasa_nu_zanum_na

# wav は作らずプロソディー結果だけ確認
./gen_long.sh --dry "Pasika-ik mau na putau a kwazai"
```

`gen_long.sh` は内部で prosody.py → gen_audio.sh と呼ぶだけなので、
結果に満足がいかなければ `prosody.py` の出力を手で直し、直接
`gen_audio.sh "Pina i, tia na, ..." pina_i_tia_...` と渡してもよいです。

## slug 変換規則

JS 側の `BasayAudio.slug()` と整合しています：

1. 英数字以外を `_` に置換
2. 先頭末尾の `_` を除去
3. 小文字化

例：`"kasul'ija m-l'asl'aseq"` → `kasul_ija_m_l_asl_aseq`
