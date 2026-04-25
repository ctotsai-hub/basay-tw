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
| **`basay_text.py`** | **表記 → slug / TTS 派生のコアモジュール（推奨）** |
| **`gen_audio.py`** | **basay_text を使った賢い音声生成ラッパー（推奨）** |
| **`build_daily_audio.py`** | **`data/daily.json` の全エントリを一括生成（推奨）** |
| `gen_audio.sh` | 1 語を IPay と 台語 の 2 音源で生成（旧来、slug を手で渡す） |
| `gen_long.sh` | 長文用ラッパー。`prosody.py` で句読点自動挿入 → `gen_audio.sh` |
| `prosody.py` | Basay 長文に `,` / `.` を自動挿入（eSpeak-NG TTS 用、旧仕様） |
| `collect_basay.py` | HTML から `data-basay="..."` 属性を抽出して manifest を生成 |
| `collect_basay.sh` | 上記 Python スクリプトの bash ラッパー |
| `build_all_audio.sh` | HTML 由来 manifest を読んで全件一括生成（v1、HTML 例文用） |
| `audio_manifest.tsv` | HTML 内の Basay 例文一覧（TEXT\tSLUG） |

## 推奨ワークフロー（v2 / 2026-04-25 以降）

「**表記**」を唯一のソースとして、slug と TTS 入力を `basay_text.py` が自動派生します。
これにより以下の三者が常に整合：

```
表記 (display)  ─┬─→ slug      （音声ファイル名）
                  └─→ tts text  （eSpeak 入力）
```

### 単体合成

```bash
# 表記 1 つを渡せば slug も TTS も自動派生
python3 gen_audio.py "Makawas ita mau Basay"
#   display: Makawas ita mau Basay
#   slug:    makawas_ita_mau_basay
#   tts:     Ma:kawas ita mau Basay
#   → audio/ipay/makawas_ita_mau_basay.wav
#   → audio/hokkien/makawas_ita_mau_basay.wav

# slug を手動上書き（表記が特殊文字を含むが、シンプルな slug にしたい時）
python3 gen_audio.py "kalili'" --slug kalili

# TTS テキストを手動上書き（プロソディを手で完璧に整えたい時）
python3 gen_audio.py "Lennaita" --tts "Le:nnaita,"

# 派生だけ確認（合成しない）
python3 gen_audio.py "Pina i tia na zijan kuwarij-an-a ni qupa" --dry-run

# 既存ファイルを上書き
python3 gen_audio.py "tsu" --force
```

### daily.json から一括生成

`data/daily.json` に新しい日付エントリを足したあとに 1 回叩けば、
未生成の音声だけが自動で合成されます。

```bash
# 未生成のみ生成（普通の使い方）
python3 build_daily_audio.py

# 何が作られるか確認だけ（合成しない）
python3 build_daily_audio.py --dry-run

# 全件強制再生成
python3 build_daily_audio.py -f
```

各エントリについて：

- `entry.word` が表記
- `entry.slug` が空でなければそれを slug 上書きとして使用
- `audio/ipay/{slug}.wav` と `audio/hokkien/{slug}.wav` が両方揃っていれば skip
- どちらか欠けていれば `gen_audio.py` を呼んで合成

### 派生規則の確認・テスト

```bash
# 派生結果を確認するだけ（合成しない）
python3 basay_text.py "Makawas ita mau Basay"

# 自己テスト
python3 basay_text.py --test
```

### slug 変換規則（v2）

1. 特殊文字置換：`ŋ`/`Ŋ`/`ʔ`/`'`/`’` → `x`、`ə` → `e`、`ɨ` → `i`
2. 小文字化
3. 英数字以外の連続 → `_`
4. 先頭・末尾の `_` を除去
5. `--slug` で手動上書き可

### TTS 派生規則（v2）

1. **①** 各ワードが子音始まりなら、最初の母音の直前に `:` を挿入。母音始まりは変更なし。
   - 例：`paman` → `p:aman`、`kwazai` → `kw:azai`、`abu` → `abu`
2. **②** `-` を `:` に置換（音節境界）
3. **③** 語末が `-ku`, `-su`, `-an`, `-ay`, `-ai`, `-ik`, `-it`, `-is` のいずれかなら直後に `,`
4. **④** スタンドアロンの `u`, `ta`, `a`, `nu` の直後に `,`
5. 文末トークンには `,` を付けない
6. `--tts` で手動上書き可

例：

| 表記 | slug | TTS |
|---|---|---|
| `Makawas ita mau Basay` | `makawas_ita_mau_basay` | `M:akawas ita m:au B:asay` |
| `Mani tisu kaman u` | `mani_tisu_kaman_u` | `M:ani t:isu, k:aman, u` |
| `Pasika-ik mau na putau a kwazai` | `pasika_ik_mau_na_putau_a_kwazai` | `P:asika:ik, m:au n:a p:utau a, kw:azai` |
| `Azasa nu zanum-na` | `azasa_nu_zanum_na` | `Azasa n:u, z:anum:na` |
| `kalili'` | `kalilix` | `k:alili'` |

## 旧来の使い方（v1、互換のため残置）

### gen_audio.sh — slug を手で渡す

### gen_audio.sh — 単体で 1 語生成

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
