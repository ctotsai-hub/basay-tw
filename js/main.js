// ============================================================
// basay.tw — 共通腳本
// ============================================================

// 1. 導覽列當前頁面高亮
(function highlightActiveNav() {
  const path = window.location.pathname.replace(/\/index\.html$/, "/");
  document.querySelectorAll("nav.site-nav a").forEach((a) => {
    const href = a.getAttribute("href").replace(/\/index\.html$/, "/");
    if (href === "/" || href === "./" || href === "../" || href === "../") {
      if (path === "/" || path.endsWith("/") && path.split("/").filter(Boolean).length === 0) {
        a.classList.add("active");
      }
    }
    const last = path.split("/").filter(Boolean).pop() || "";
    if (href.includes(last) && last !== "") {
      a.classList.add("active");
    }
  });
})();

// 2. 今日的巴賽語（Daily widget）+ Back number archive
//    data/daily.json の形式: { "YYYY-MM-DD": { word, gloss, usage }, default: {...} }
//
//    動作:
//      ・today のキーが無ければ直近の過去日のエントリを使用（fill-forward）
//      ・[data-daily-widget] : 今日の一句を表示
//      ・[data-daily-archive]: 過去 30 日分を日付降順で描画（音声ボタン付き）
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function loadDaily() {
  const widget = document.querySelector("[data-daily-widget]");
  const archive = document.querySelector("[data-daily-archive]");
  if (!widget && !archive) return;

  const host = widget || archive;
  const root = (host.dataset.root || ".").replace(/\/$/, "");

  let data;
  try {
    const res = await fetch(root + "/data/daily.json", { cache: "no-cache" });
    if (!res.ok) throw new Error("daily.json not found");
    data = await res.json();
  } catch (err) {
    console.warn("Daily:", err);
    return;
  }

  const today = new Date().toISOString().slice(0, 10);

  const dateKeys = Object.keys(data)
    .filter(function (k) { return /^\d{4}-\d{2}-\d{2}$/.test(k); })
    .sort();

  function findEffectiveKey(target) {
    var latest = null;
    for (var i = 0; i < dateKeys.length; i++) {
      var k = dateKeys[i];
      if (k <= target) latest = k;
      else break;
    }
    return latest;
  }

  // Daily widget の更新
  if (widget) {
    var key = findEffectiveKey(today);
    var entry = (key && data[key]) || data.default;
    if (entry) {
      var dateEl = widget.querySelector("[data-daily-date]");
      var wordEl = widget.querySelector("[data-daily-word]");
      var glossEl = widget.querySelector("[data-daily-gloss]");
      var usageEl = widget.querySelector("[data-daily-usage]");
      if (dateEl) dateEl.textContent = today;
      if (wordEl) {
        wordEl.textContent = entry.word || "";
        wordEl.dataset.basay = entry.word || "";
        var next = wordEl.nextElementSibling;
        if (next && next.classList && next.classList.contains("basay-audio-btns")) {
          next.remove();
        }
        delete wordEl.dataset.basayAudioBound;
      }
      if (glossEl) glossEl.textContent = entry.gloss || "";
      if (usageEl) usageEl.textContent = entry.usage || "";
      if (wordEl && window.BasayAudio) window.BasayAudio.attachButtons(wordEl);
    }
  }

  // Archive
  if (archive) {
    var currentKey = findEffectiveKey(today);
    var pastKeys = dateKeys
      .filter(function (k) { return k < (currentKey || today); })
      .reverse()
      .slice(0, 30);

    if (pastKeys.length === 0) {
      archive.innerHTML = '<p class="da-empty">（まだ過去のエントリがありません）</p>';
    } else {
      archive.innerHTML = pastKeys.map(function (k) {
        var e = data[k] || {};
        var word = escapeHtml(e.word);
        var gloss = escapeHtml(e.gloss);
        var usage = escapeHtml(e.usage);
        return '<article class="daily-archive-item">' +
          '<div class="da-date">' + k + '</div>' +
          '<div class="da-word" data-basay="' + word + '">' + word + '</div>' +
          '<div class="da-gloss">' + gloss + '</div>' +
          (usage ? '<div class="da-usage">' + usage + '</div>' : '') +
          '</article>';
      }).join("");

      if (window.BasayAudio) {
        archive.querySelectorAll("[data-basay]").forEach(function (el) {
          window.BasayAudio.attachButtons(el);
        });
      }
    }
  }
}

document.addEventListener("DOMContentLoaded", function () {
  setTimeout(loadDaily, 0);
});
