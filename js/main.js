// ============================================================
// basay.tw — 共通腳本
// ============================================================

// 1. 導覽列當前頁面高亮
(function highlightActiveNav() {
  const path = window.location.pathname.replace(/\/index\.html$/, "/");
  document.querySelectorAll("nav.site-nav a").forEach((a) => {
    const href = a.getAttribute("href").replace(/\/index\.html$/, "/");
    // 根目錄特例
    if (href === "/" || href === "./" || href === "../" || href === "../") {
      if (path === "/" || path.endsWith("/") && path.split("/").filter(Boolean).length === 0) {
        a.classList.add("active");
      }
    }
    // 其他頁：比對最後一段路徑
    const last = path.split("/").filter(Boolean).pop() || "";
    if (href.includes(last) && last !== "") {
      a.classList.add("active");
    }
  });
})();

// 2. 今日的巴賽語（Daily widget）
//    若頁面中有 data-daily-widget 元素，從 data/daily.json 取得當日詞。
//    檔案格式：{ "YYYY-MM-DD": { word, gloss, usage }, default: {...} }
async function loadDailyWord() {
  const host = document.querySelector("[data-daily-widget]");
  if (!host) return;

  // 相對路徑解析：根據 host 的 data-root
  const root = host.dataset.root || ".";
  try {
    const res = await fetch(`${root}/data/daily.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error("daily.json not found");
    const data = await res.json();

    const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    const entry = data[today] || data.default;
    if (!entry) return;

    host.querySelector("[data-daily-date]").textContent = today;
    host.querySelector("[data-daily-word]").textContent = entry.word;
    host.querySelector("[data-daily-gloss]").textContent = entry.gloss;
    host.querySelector("[data-daily-usage]").textContent = entry.usage || "";
  } catch (err) {
    console.warn("Daily widget:", err);
  }
}

document.addEventListener("DOMContentLoaded", loadDailyWord);
