// ============================================================
// basay.tw — 辭典檢索（純前端）
// data/dictionary.json 結構：
// [
//   { "id": "1", "basay": "ranum", "pos": "n.", "zh": ["水"], "ja": ["みず"], "en": ["water"], "source": "Li 2001" },
//   ...
// ]
// ============================================================

(function () {
  const form = document.getElementById("dict-form");
  const input = document.getElementById("dict-query");
  const lang = document.getElementById("dict-lang");
  const results = document.getElementById("dict-results");
  if (!form || !results) return;

  let DATA = [];
  let loaded = false;

  async function load() {
    if (loaded) return;
    try {
      const res = await fetch("../data/dictionary.json", { cache: "no-cache" });
      DATA = await res.json();
      loaded = true;
      renderHint(`已載入 ${DATA.length} 筆詞條。輸入關鍵字並按搜尋。`);
    } catch (e) {
      renderHint("⚠️ 無法載入辭典資料。", true);
    }
  }

  function renderHint(msg, isErr = false) {
    results.innerHTML = `<p class="dict-empty" style="${isErr ? "color:#c86d4a" : ""}">${msg}</p>`;
  }

  function matches(entry, q, field) {
    const needle = q.toLowerCase().trim();
    if (!needle) return false;

    if (field === "basay") {
      return entry.basay && entry.basay.toLowerCase().includes(needle);
    }
    if (field === "any") {
      const hay = [
        entry.basay,
        ...(entry.zh || []),
        ...(entry.ja || []),
        ...(entry.en || []),
      ].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(needle);
    }
    // zh / ja / en
    const list = entry[field] || [];
    return list.some((s) => String(s).toLowerCase().includes(needle));
  }

  function renderEntries(list) {
    if (list.length === 0) {
      renderHint("沒有符合的詞條。（試試看其他拼寫，或以中文 / 日文 / 英文搜尋）");
      return;
    }
    results.innerHTML = list.map((e) => {
      const zh = (e.zh || []).join("、") || "—";
      const ja = (e.ja || []).join("、");
      const en = (e.en || []).join(", ");
      const src = e.source ? `<span class="source">出處：${e.source}</span>` : "";
      return `
        <div class="dict-entry">
          <span class="headword">${escapeHtml(e.basay)}</span>
          ${e.pos ? `<span class="pos">${escapeHtml(e.pos)}</span>` : ""}
          <ul class="senses">
            <li><strong>中：</strong>${escapeHtml(zh)}</li>
            ${ja ? `<li><strong>日：</strong>${escapeHtml(ja)}</li>` : ""}
            ${en ? `<li><strong>EN：</strong>${escapeHtml(en)}</li>` : ""}
          </ul>
          ${src}
        </div>
      `;
    }).join("");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    await load();
    const q = input.value;
    if (!q.trim()) { renderHint("請輸入關鍵字。"); return; }
    const field = lang.value;
    const hits = DATA.filter((e) => matches(e, q, field)).slice(0, 200);
    renderEntries(hits);
  });

  // 頁面初始：預先載入 & 顯示提示
  load();
})();
