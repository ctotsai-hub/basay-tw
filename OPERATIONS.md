# basay.tw 日常運用手順

basay.tw の日次・随時の運用フロー。
最終更新：2026-04-25（slug/TTS 自動派生 v2 対応）

---

## 0. 前提・全体像

**ホスティング**：GitHub Pages（独自ドメイン `basay.tw`、CNAME 済み）
**デプロイ**：`git push` → GitHub Pages が自動配信
**作業ディレクトリ**：

```
C:\Users\user\Downloads\basay-grammar\webpage\凱達格蘭（巴賽語） ～從記憶到再生～\
```

WSL からは：

```
/mnt/c/Users/user/Downloads/basay-grammar/webpage/凱達格蘭（巴賽語） ～從記憶到再生～
```

**主な構成**：

| パス | 役割 |
|---|---|
| `index.html` | トップページ |
| `grammar/index.html` | バサイ語文法基本 |
| `education/index.html` | 教育推進（会話集・本日のバサイ語） |
| `education/phrasebook/` | 会話集ページ＋音声 |
| `data/daily.json` | 「今日の巴賽語」のデータソース |
| `js/basay-text.js` | 表記 → slug / TTS 派生（JS 側） |
| `js/audio.js` | 音声再生ボタン制御 |
| `js/main.js` | 共通スクリプト（Daily widget 含む） |
| `scripts/` | 音声生成スクリプト（Python / bash） |
| `education/phrasebook/audio/ipay/` | IPay 音源（`bsy` ボイス） |
| `education/phrasebook/audio/hokkien/` | 台語適合音源（`bsystd` ボイス） |

---

## 1. 日次運用：「今日の巴賽語」を更新

### Step 1. `data/daily.json` に新エントリを追加

```jsonc
{
  "default": { "word": "Makawas ita mau Basay", "gloss": "...", "usage": "..." },
  "2026-04-21": { "word": "lusa",   "gloss": "二（two）",      "usage": "nia-lusa-na — 兩個人。" },
  "2026-04-22": { "word": "zanum",  "gloss": "水（water）",    "usage": "mataru zanum — 我（要）水。" },
  "2026-04-25": {
    "word":  "新しい表記",
    "gloss": "言語学グロス",
    "usage": "用例（繁體字）"
  }
}
```

ポイント：

- キーは `YYYY-MM-DD`
- 日付が抜けてもページは fill-forward で前回の内容を表示するため、毎日埋める必要はない
- 特殊文字を含む語で旧 slug 互換が必要な場合のみ `"slug": "kalili"` を併記

### Step 2. 音声を生成

**推奨：daily 一括生成**

```bash
cd "/mnt/c/Users/user/Downloads/basay-grammar/webpage/凱達格蘭（巴賽語） ～從記憶到再生～/scripts"

# 何が作られるか確認（合成しない）
python3 build_daily_audio.py --dry-run

# 未生成のものだけ作る
python3 build_daily_audio.py
```

`daily.json` 全エントリを走査し、`audio/ipay/{slug}.wav` と `audio/hokkien/{slug}.wav` が両方揃っていない分だけ合成します。明日以降に何日分まとめて追加しても、これ 1 発で OK。

**個別に 1 件だけ生成したい時**

```bash
# 表記 1 つ渡せば slug も TTS も自動派生
python3 gen_audio.py "新しい表記"

# 派生だけ確認
python3 gen_audio.py "新しい表記" --dry-run

# 既存ファイルを上書き
python3 gen_audio.py "新しい表記" --force
```

`audio_manifest.tsv` も自動更新される。

### Step 3. ローカルで確認

`index.html` をブラウザで開き、Daily widget の表示と音声ボタン（▶ IPay / ▶ 台語）を確認。

### Step 4. コミット & プッシュ

```bash
cd "/mnt/c/Users/user/Downloads/basay-grammar/webpage/凱達格蘭（巴賽語） ～從記憶到再生～"
git add data/daily.json education/phrasebook/audio/
git commit -m "Daily: YYYY-MM-DD 〇〇〇〇"
git push
```

数十秒〜2 分で `https://basay.tw/` に反映される。

---

## 2. 随時運用：本文・ニュース翻訳の追加

### 2-1. ページ本文に Basay 例文を埋め込む

HTML に `data-basay` 属性を付けると、ロード時に自動で音声ボタンが付与される：

```html
<p class="basay-line" data-basay="Makawas ita mau Basay">
  Makawas ita mau Basay
</p>
```

slug は `BasayText.slug()` が自動派生。**特殊文字（`'`, `ŋ`, `ʔ`）を含み旧 slug を維持したい既存例文のみ** `data-slug` で上書き：

```html
<p data-basay="kasul'ija m-l'asl'aseq" data-slug="kasul_ija_m_l_asl_aseq">
  kasul'ija m-l'asl'aseq
</p>
```

### 2-2. 音声を生成

```bash
cd scripts
python3 gen_audio.py "Makawas ita mau Basay"
```

`data-slug` で旧 slug を指定した場合は、対応する `.wav` がすでに存在するはずなので新規生成は不要。

### 2-3. まとめて再生成したいとき

```bash
# 1. ページから data-basay 属性を抽出して manifest を更新
./collect_basay.sh

# 2. manifest 全件を一括生成（既存はスキップ）
./build_all_audio.sh

# 3. 強制上書き
./build_all_audio.sh -f
```

### 2-4. コミット

```bash
git add education/index.html education/phrasebook/audio/
git commit -m "Add news article: 〇〇"
git push
```

---

## 3. 表記 / slug / TTS の派生規則（v2）

唯一のソースは「**表記**」。`scripts/basay_text.py` と `js/basay-text.js` が同じ規則で slug と TTS を派生する。

### slug 規則

1. 特殊文字置換：`ŋ`/`Ŋ`/`ʔ`/`'`/`’` → `x`、`ə` → `e`、`ɨ` → `i`
2. 小文字化
3. 英数字以外 → `_`
4. 先頭・末尾の `_` を除去
5. `--slug` または `data-slug` で手動上書き可

### TTS 規則

1. **①** 各ワードが子音始まりなら、最初の母音の直前に `:` を挿入。母音始まりは変更なし。
   - `paman` → `p:aman`、`abu` → `abu`、`kwazai` → `kw:azai`
2. **②** `-` を `:` に置換
3. **③** 語末が `-ku`, `-su`, `-an`, `-ay`, `-ai`, `-ik`, `-it`, `-is` なら `,`
4. **④** スタンドアロンの `u`, `ta`, `a`, `nu` の直後に `,`
5. 文末トークンには `,` を付けない
6. `--tts` で手動上書き可

### 規則を確認したい時

```bash
cd scripts

# 派生結果を確認（合成しない）
python3 basay_text.py "Makawas ita mau Basay"

# 自己テスト
python3 basay_text.py --test
```

JS 側のテストは `index.html` をブラウザで開き、DevTools コンソールで：

```js
BasayText.derive("Makawas ita mau Basay")
// → {display, slug: "makawas_ita_mau_basay", tts: "M:akawas ita m:au B:asay"}
```

---

## 4. 規則を変更した時

`basay_text.py` と `basay-text.js` は **常に同期** させる。変更フロー：

1. `scripts/basay_text.py` の `TEST_CASES` にケースを追加
2. ロジック修正
3. `python3 basay_text.py --test` で 全件 pass を確認
4. 同じ修正を `js/basay-text.js` に適用
5. `scripts/README.md` の規則説明・例表も更新
6. 既存 wav に影響を与えたくない場合は、影響範囲のページに `data-slug` を付けて旧 slug 固定
7. コミット：

```bash
git add scripts/basay_text.py js/basay-text.js scripts/README.md
git commit -m "Update slug/TTS rule: 〇〇"
git push
```

---

## 5. 論文・研究成果の掲載

研究成果ページは別途 `research/` などの配下に追加（現状未整備）。
構造の方針：

- `research/index.html` に索引
- 各論文は `research/{slug}/` に PDF または HTML
- PDF はリポジトリに直接置く（GitHub Pages から配信可能）
- DOI / 著者 / 年 / 概要を索引に必ず記載

---

## 6. 辞書検索

辞書検索機能は未実装。実装時の想定：

- `data/dictionary.json`（または `.tsv`）を単一ソース
- `dict/index.html` で fetch → クライアント側でインクリメンタル絞り込み
- 各エントリにも `data-basay` を付与し共通の音声ボタンを再利用

---

## 7. トラブルシュート

### 「Everything up-to-date」と言われる

`git add` だけして `git commit` を忘れている可能性。

```bash
git status              # 何が staged / unstaged かを確認
git commit -m "..."     # 必ずコミット
git push
```

### `git add` でパスエラー

カレントディレクトリがリポジトリルートでない可能性。

```bash
cd "/mnt/c/Users/user/Downloads/basay-grammar/webpage/凱達格蘭（巴賽語） ～從記憶到再生～"
pwd
```

### 音声が再生されない

1. ブラウザ DevTools → Network で `.wav` の 404 を確認
2. slug 名がページの `data-slug` または自動派生と一致しているか
3. ファイルがコミットされているか（`git status` で untracked になっていないか）
4. eSpeak-NG のボイス定義（`bsy` / `bsystd`）が登録されているか

### バックアップファイル（`daily - 複製.json` 等）が untracked

不要であれば削除、残すなら `.gitignore` に追加：

```bash
# .gitignore
*\ -\ 複製.*
*.bak
```

### 派生規則変更後にテストが古いまま

Python の `__pycache__/*.pyc` をクリア：

```bash
find scripts -name __pycache__ -exec rm -rf {} +
python3 scripts/basay_text.py --test
```

---

## 8. 推奨チェックリスト（公開前）

- [ ] `python3 scripts/basay_text.py --test` が全件 pass
- [ ] ローカルでトップページ・文法・教育の各ページがエラーなく表示
- [ ] DevTools Console にエラーが出ていない
- [ ] 新規追加した `data-basay` の音声ボタンから IPay / 台語 ともに再生できる
- [ ] `git status` に意図しない変更が無い
- [ ] コミットメッセージが日付・内容を含む（例：`Daily: 2026-04-25 zanum`）
