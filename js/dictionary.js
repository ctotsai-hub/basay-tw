// ============================================================
// basay.tw - 辭典檢索（純前端、GitHub 管理データ対応）
// 読み込むデータ：
//   data/dictionary.json        ← エントリ本体
//   dictionary/categories.json  ← 番号 → 完全ラベル
// エントリ構造：
//   { id, basay, category, zh:[], ja:[], en:[], source, original?, remark?, audio? }
//   audio: { slug, ipay?: "dictionary/audio/ipay/...mp3", hokkien?: "..." }
// ============================================================

(function () {
  const form       = document.getElementById("dict-form");
  const input      = document.getElementById("dict-query");
  const langSel    = document.getElementById("dict-lang");
  const catSel     = document.getElementById("dict-category");
  const sourceSel  = document.getElementById("dict-source");
  const idInput    = document.getElementById("dict-id");
  const results    = document.getElementById("dict-results");
  const statusEl   = document.getElementById("dict-status");
  if (!form || !results) return;

  const RESULT_LIMIT = 200;
  const SOURCE_LABEL = {
    B:   "Basay",
    T:   "Trobiawan",
    M:   "Trobiawan-m",
    S:   "Trobiawan-s",
    V:   "台語",
    PAN: "南島祖語 (Proto-Austronesian)",
    L:   "外來語 (Loanword)",   // ← 追加
    N:   "新造語 (Neologism)",  // ← 追加
  };

  let DATA = [];
  let CATEGORIES = {};
  let loaded = false;
  let loading = null;

  let currentAudio = null;
  function playAudio(url) {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    }
    currentAudio = new Audio(url);
    currentAudio.play().catch((err) => {
      setStatus(`⚠️ 無法播放音檔：${url}`, true);
      console.error("audio playback failed", url, err);
    });
  }

  function setStatus(msg, isErr = false) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("dict-status--err", !!isErr);
  }

  async function load() {
    if (loaded) return;
    if (loading) return loading;
    loading = (async () => {
      try {
        const [dictRes, catRes] = await Promise.all([
          fetch("../data/dictionary.json", { cache: "no-cache" }),
          fetch("../dictionary/categories.json", { cache: "no-cache" }),
        ]);
        DATA = await dictRes.json();
        try {
          CATEGORIES = await catRes.json();
        } catch (e) {
          CATEGORIES = {};
          console.warn("categories.json missing or invalid", e);
        }
        populateCategoryFilter();
        loaded = true;
        setStatus(`已載入 ${DATA.length.toLocaleString()} 筆詞條（${Object.keys(CATEGORIES).length} 類）。`);
        renderHint(`輸入關鍵字或選擇類別後按「搜尋」。`);
      } catch (e) {
        console.error(e);
        renderHint("⚠️ 無法載入辭典資料。", true);
      }
    })();
    return loading;
  }

  function populateCategoryFilter() {
    if (!catSel) return;
    const nums = Object.keys(CATEGORIES).sort();
    for (const num of nums) {
      const opt = document.createElement("option");
      opt.value = num;
      opt.textContent = CATEGORIES[num];
      catSel.appendChild(opt);
    }
  }

  function renderHint(msg, isErr = false) {
    results.innerHTML =
      `<p class="dict-empty" style="${isErr ? "color:#c86d4a" : ""}">${msg}</p>`;
  }

  // カタカナ→ひらがな変換（U+30A1–U+30F6）
  function toHira(s) {
    return String(s).replace(/[ァ-ヶ]/g, (c) =>
      String.fromCharCode(c.charCodeAt(0) - 0x60)
    );
  }

  // 正規化：小文字化 ＋ カタカナ→ひらがな（日本語・混合テキスト全般に適用）
  function norm(s) {
    return toHira(String(s).toLowerCase());
  }

  function matches(entry, q, field) {
    if (!q) return true;
    const raw = q.trim();
    if (!raw) return true;

    if (field === "basay") {
      return entry.basay && entry.basay.toLowerCase().includes(raw.toLowerCase());
    }
    if (field === "ja") {
      const needle = norm(raw);
      return (entry.ja || []).some((s) => norm(s).includes(needle));
    }
    if (field === "any") {
      // 非日本語フィールド：通常小文字比較
      const needleLo = raw.toLowerCase();
      const hayLo = [
        entry.basay, entry.original,
        ...(entry.zh || []), ...(entry.en || []),
      ].filter(Boolean).join(" ").toLowerCase();

      // 日本語フィールド＋remark：カナ正規化して比較
      const needleN = norm(raw);
      const hayN = [
        ...(entry.ja || []),
        entry.remark,
      ].filter(Boolean).map(norm).join(" ");

      return hayLo.includes(needleLo) || hayN.includes(needleN);
    }
    // zh / en などフィールド指定の場合
    const needle = norm(raw);
    const list = entry[field] || [];
    return list.some((s) => norm(s).includes(needle));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function categoryLabel(num) {
    if (!num) return "";
    return CATEGORIES[num] || num;
  }

  function sourceBadge(code) {
    if (!code) return "";
    const label = SOURCE_LABEL[code] || code;
    return `<span class="src-badge src-${code}" title="${escapeHtml(label)}">${escapeHtml(code)}</span>`;
  }

  function audioButtons(audio) {
    audio = audio || {};
    const mkBtn = (key, cls, label, longTitle) => {
      const url = audio[key];
      if (url) {
        return `<button type="button" class="audio-btn ${cls}" data-audio="${escapeHtml(url)}" title="${escapeHtml(longTitle)}">▶ ${escapeHtml(label)}</button>`;
      }
      return `<button type="button" class="audio-btn ${cls} audio-btn--pending" disabled title="音檔尚未生成">▶ ${escapeHtml(label)}<span class="audio-pending-tag">準備中</span></button>`;
    };
    return mkBtn("ipay",    "",                "Ipay",  "Ipay 語音（巴賽語 TTS）")
         + mkBtn("hokkien", "audio-btn--alt",  "台語",  "台語語音（Hokkien TTS）");
  }

  function renderEntries(list) {
    if (list.length === 0) {
      renderHint("沒有符合的詞條。（試試看其他拼寫、或切換語言／類別）");
      return;
    }

    const html = list.map((e) => {
      const cat = e.category ? categoryLabel(e.category) : "";
      const zh = (e.zh || []).join("、");
      const ja = (e.ja || []).join("、");
      const en = (e.en || []).join(", ");
      const showOriginal = !!e.original;

      return `
        <div class="dict-entry">
          <div class="dict-entry-head">
            <span class="headword">${escapeHtml(e.basay)}</span>
            ${e.id ? `<span class="entry-id">${escapeHtml(e.id)}</span>` : ""}
            ${cat ? `<span class="pos">${escapeHtml(cat)}</span>` : ""}
            ${sourceBadge(e.source)}
            ${audioButtons(e.audio)}
          </div>
          <ul class="senses">
            ${zh ? `<li><strong>中：</strong>${escapeHtml(zh)}</li>` : ""}
            ${ja ? `<li><strong>日：</strong>${escapeHtml(ja)}</li>` : ""}
            ${en ? `<li><strong>EN：</strong>${escapeHtml(en)}</li>` : ""}
          </ul>
          ${showOriginal ? `<div class="dict-original">IPA：<span>${escapeHtml(e.original)}</span></div>` : ""}
          ${e.remark ? `<div class="dict-remark">${escapeHtml(e.remark).replace(/\n/g, "<br>")}</div>` : ""}
        </div>
      `;
    }).join("");

    results.innerHTML = html;

    results.querySelectorAll(".audio-btn:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => {
        const url = btn.getAttribute("data-audio");
        if (url) playAudio(`../${url}`);
      });
    });
  }

  function runSearch() {
    const q      = (input.value || "").trim();
    const field  = langSel   ? langSel.value        : "any";
    const cat    = catSel    ? catSel.value          : "";
    const source = sourceSel ? sourceSel.value.trim(): "";
    const idQ    = idInput   ? idInput.value.trim()  : "";

    // 何も入力されていない場合はヒントを表示して終了
    if (!q && !cat && !source && !idQ) {
      renderHint("請輸入關鍵字或選擇類別。");
      setStatus("");
      return;
    }

    let hits = DATA;
    if (cat)    hits = hits.filter((e) => e.category === cat);
    if (source) hits = hits.filter((e) => (e.source || "").trim() === source);
    if (idQ)    hits = hits.filter((e) => e.id != null && String(e.id).includes(idQ));
    if (q)      hits = hits.filter((e) => matches(e, q, field));

    const total = hits.length;
    const shown = hits.slice(0, RESULT_LIMIT);
    renderEntries(shown);
    if (total > RESULT_LIMIT) {
      setStatus(`命中 ${total.toLocaleString()} 筆，僅顯示前 ${RESULT_LIMIT} 筆。請縮小範圍。`);
    } else {
      setStatus(`命中 ${total.toLocaleString()} 筆。`);
    }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    await load();
    if (!loaded) return;
    runSearch();
  });

  // セレクト変更時に自動検索
  const autoSearchSelects = [catSel, sourceSel].filter(Boolean);
  for (const sel of autoSearchSelects) {
    sel.addEventListener("change", async () => {
      await load();
      if (!loaded) return;
      runSearch();
    });
  }

  // ID入力欄：入力後500msでオートサーチ（Enterでも可）
  if (idInput) {
    let idTimer = null;
    idInput.addEventListener("input", async () => {
      clearTimeout(idTimer);
      idTimer = setTimeout(async () => {
        await load();
        if (!loaded) return;
        runSearch();
      }, 500);
    });
  }

  load();
})();
