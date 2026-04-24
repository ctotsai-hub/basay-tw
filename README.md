# basay.tw — 凱達格蘭（巴賽語）〜從記憶到再生〜

> 凱達格蘭族 Basay 語言的文法、教育、研究與辭典平台。  
> **Live site:** [https://basay.tw](https://basay.tw)（待部署）

---

## 🎯 計畫宗旨

1. **保存** — 彙整 Ogawa、Ferrell、李壬癸等先行研究的巴賽語語料。  
2. **教育** — 本日的巴賽語、會話集、新聞翻譯，讓語言走進日常。  
3. **研究** — 提供論文索引與田野調查報告彙整。  
4. **再生** — 以開放、可引用的方式，讓族人與學習者共同參與。

完整企劃請見 [`PLAN.md`](./PLAN.md)。

---

## 📁 專案結構

```
.
├── index.html              # 首頁（Hero、四大區塊、今日的巴賽語）
├── grammar/index.html      # 文法基本（音韻・語序・代名詞・動詞）
├── education/index.html    # 教育推進（會話集・每日新聞翻譯）
├── research/index.html     # 研究成果（論文、田野調查、歷史文獻）
├── dictionary/index.html   # 辭典檢索（Basay/中/日/英 互查）
├── about/index.html        # 關於本站
├── 404.html                # 錯誤頁
│
├── css/style.css           # 全站樣式（凱達格蘭土地色調）
├── js/main.js              # 共通 JS（導覽高亮、每日詞 widget）
├── js/dictionary.js        # 辭典檢索邏輯（前端搜尋）
│
├── data/
│   ├── dictionary.json     # 辭典資料（陣列結構）
│   └── daily.json          # 每日的巴賽語
│
├── CNAME                   # 自訂網域：basay.tw
├── .nojekyll               # 關閉 GitHub Pages 的 Jekyll 處理
├── .github/workflows/pages.yml  # 自動部署到 GitHub Pages
└── PLAN.md                 # 企劃書
```

---

## 🚀 部署到 basay.tw

### Step 1 — 推到 GitHub

```bash
cd "<本專案資料夾>"
git init
git add .
git commit -m "chore: initial scaffold for basay.tw"
git branch -M main
git remote add origin git@github.com:<你的帳號或組織>/<repo-name>.git
git push -u origin main
```

### Step 2 — 啟用 GitHub Pages

- 到 GitHub repo → **Settings → Pages**
- Source 選 **GitHub Actions**（已包含 `.github/workflows/pages.yml`）
- 推送 main branch 後會自動部署

### Step 3 — 綁定自訂網域 basay.tw

在你的 DNS 供應商（例如 TWNIC 或 Cloudflare）設定：

| 類型  | 主機 | 值 |
|-------|------|-----|
| A     | @ | `185.199.108.153` |
| A     | @ | `185.199.109.153` |
| A     | @ | `185.199.110.153` |
| A     | @ | `185.199.111.153` |
| CNAME | www | `<你的帳號>.github.io` |

專案根目錄已附 `CNAME` 檔案，內容為 `basay.tw`，GitHub 會自動辨識。

開啟 **Settings → Pages → Enforce HTTPS** 以啟用 HTTPS。

---

## ✍️ 內容更新指南

### 加新詞條（Notion 主 + JSON 快取）

詞條的 **主資料庫維護於 Notion**：  
<https://basay.notion.site/234ef706551c8041af41fe6986178006?v=234ef706551c81739e90000ca14eabbd>

GitHub 上的 `data/dictionary.json` 是離線檢索用的快取。定期同步流程：

1. 在 Notion 辭典資料庫新增 / 修訂詞條。
2. Notion 右上 **⋯ → Export → CSV**，選「Current view」。
3. 將 CSV 轉為本站格式（可用下列 Node 片段或自寫腳本）：

   ```js
   // scripts/notion-to-json.mjs（建議日後建立）
   import fs from "node:fs"; import { parse } from "csv-parse/sync";
   const rows = parse(fs.readFileSync("notion-export.csv"), { columns: true });
   const out = rows.map((r, i) => ({
     id: String(i + 1).padStart(3, "0"),
     basay: r["Basay"], pos: r["POS"],
     zh: (r["中文"] || "").split(/[、,]/).filter(Boolean),
     ja: (r["日本語"] || "").split(/[、,]/).filter(Boolean),
     en: (r["English"] || "").split(/[,，]/).filter(Boolean),
     source: r["Source"],
   }));
   fs.writeFileSync("data/dictionary.json", JSON.stringify(out, null, 2));
   ```

4. `git commit && git push` — GitHub Actions 自動部署更新後的辭典。

**今後の自動化の選択肢：**
- **Notion API 直讀**：若設定 Integration Token，可改為每日以 GitHub Actions 呼叫 Notion API → 自動寫入 JSON → 自動 commit。
- **手動コピーでも十分**：資料量が小さい間は、手動エクスポート＋スクリプトで十分運用可能。

#### 手動で 1 件だけ追加する場合
直接編輯 `data/dictionary.json`：

```json
{
  "id": "021",
  "basay": "______",
  "pos": "n.",
  "zh": ["______"],
  "ja": ["______"],
  "en": ["______"],
  "source": "作者 年份"
}
```

### 更新本日的巴賽語
編輯 `data/daily.json`，以 `YYYY-MM-DD` 為 key 加入當日詞條。沒有特定日期時會 fallback 到 `default`。

### 新增論文
在 `research/index.html` 中複製任一 `<article class="paper">` 區塊並修改內容即可。
如文獻量龐大，可改為從 `data/papers.json` 載入渲染（類似 dictionary 的作法）。

### 修訂文法章節
直接編輯 `grammar/index.html`。所有未審訂的拼寫請以 `⟨?⟩` 或 `⟨…⟩` 標記。

---

## 🛠 本地預覽

純靜態網站，任一 HTTP server 即可：

```bash
# Python 3
python3 -m http.server 8080
# 開瀏覽器 → http://localhost:8080
```

直接用檔案協定（`file://`）開啟也能看大部分頁面，
但 **辭典檢索頁** 需要 `fetch()` 載入 JSON，請務必透過 HTTP server 預覽。

---

## 📜 授權

- **程式碼** — MIT License  
- **內容（文字・語料彙整）** — CC BY-NC-SA 4.0  
- 語料原作者（Ogawa、Ferrell、李壬癸等）之著作權依其原授權保留。

---

## 🙏 致謝

本站站在眾多先行研究者的肩膀上：
- Paul Jen-kuei Li（李壬癸）
- Raleigh Ferrell
- 小川尚義（Ogawa Naoyoshi）
- 17 世紀西班牙道明會傳教士
- 與所有凱達格蘭族人、後裔、研究者

> *mataru Basay — 我們（需要）巴賽語*
