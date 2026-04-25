// ============================================================
// basay.tw — 共有音聲播放組件
// ------------------------------------------------------------
// 用法（自動）:
//   <span class="basay-word" data-basay="kita' na Vali">kita' na Vali</span>
//
// 用法（slug を手動上書き、ファイル名と表記が違う場合）:
//   <span class="basay-word"
//         data-basay="kalili'"
//         data-slug="kalili">kalili'</span>
//
// data-basay があるすべての要素に IPay / 台語 ボタンが自動付与されます。
//
// 音聲檔案慣例:
//   /education/phrasebook/audio/{ipay|hokkien}/{slug}.wav
//   slug は BasayText.slug() で派生（scripts/basay_text.py と同期）
// ============================================================

(function () {
  "use strict";

  // ─────── 音聲メタ情報 ───────
  const VOICES = {
    ipay:    { dir: "ipay",    tag: "IPay",  label: "IPay 歷史復元（bsy）",          emoji: "🔵" },
    hokkien: { dir: "hokkien", tag: "台語", label: "台語適合・Lobanov（bsystd）",   emoji: "🟢" },
  };

  // ─────── 共有ライブラリへの相対パス ───────
  // ページの <body data-audio-root="..."> または <html> のいずれかで指定。
  // 未指定時は "../education/phrasebook/audio" を仮定。
  function audioRoot() {
    const el = document.body;
    if (el && el.dataset.audioRoot) return el.dataset.audioRoot.replace(/\/$/, "");
    // Root page heuristic: /index.html は "./education/phrasebook/audio" を用いる
    return "../education/phrasebook/audio";
  }

  // ─────── ユーティリティ ───────
  // BasayText.slug() がロード済みならそれを使用、そうでなければフォールバック
  function slug(s, manual) {
    if (window.BasayText && typeof window.BasayText.slug === "function") {
      return window.BasayText.slug(s, manual);
    }
    if (manual) return String(manual).trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
    return String(s || "")
      .replace(/[ŋŊʔ'\u2019]/g, "x")
      .replace(/ə/g, "e")
      .replace(/ɨ/g, "i")
      .replace(/[^a-zA-Z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .toLowerCase();
  }

  // ─────── 音聲状態 ───────
  const STORAGE_KEY = "basay.voice";
  function currentVoice() {
    try { return sessionStorage.getItem(STORAGE_KEY) || "ipay"; }
    catch (e) { return "ipay"; }
  }
  function setVoice(v) {
    if (!VOICES[v]) return;
    try { sessionStorage.setItem(STORAGE_KEY, v); } catch (e) {}
    document.querySelectorAll(".basay-voice-switcher").forEach(upd => {
      upd.querySelectorAll("[data-voice]").forEach(b => {
        b.classList.toggle("active", b.dataset.voice === v);
      });
    });
    const st = document.getElementById("basay-voice-status");
    if (st) st.textContent = "現在：" + VOICES[v].label;
  }

  // ─────── 再生 ───────
  let currentAudio = null;
  function play(text, voice, btn, manualSlug) {
    const s = slug(text, manualSlug);
    if (!s) return;
    const url = audioRoot() + "/" + VOICES[voice].dir + "/" + s + ".wav";

    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }
    document.querySelectorAll(".basay-play.playing").forEach(b => b.classList.remove("playing"));

    const a = new Audio(url);
    currentAudio = a;
    if (btn) btn.classList.add("loading");
    a.oncanplay = () => {
      if (btn) { btn.classList.remove("loading"); btn.classList.add("playing"); }
      a.play().catch(() => { if (btn) btn.classList.remove("playing"); });
    };
    a.onended = () => { if (btn) btn.classList.remove("playing"); };
    a.onerror = () => {
      if (btn) {
        btn.classList.remove("loading", "playing");
        btn.classList.add("missing");
        btn.title = "音源準備中：" + url;
        setTimeout(() => btn.classList.remove("missing"), 1800);
      }
    };
  }

  // ─────── ボタン生成 ───────
  function makeButton(voice, text, manualSlug) {
    const v = VOICES[voice];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "basay-play basay-play--" + voice;
    btn.dataset.voice = voice;
    btn.innerHTML = '<span class="play-emoji">' + v.emoji + '</span><span class="play-label">' + v.tag + '</span>';
    btn.title = v.label + " — 播放「" + text + "」";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      play(text, voice, btn, manualSlug);
    });
    return btn;
  }

  function attachButtons(el) {
    if (el.dataset.basayAudioBound === "1") return;
    const text = el.dataset.basay || el.textContent.trim();
    if (!text) return;
    const manualSlug = el.dataset.slug || null;
    const wrap = document.createElement("span");
    wrap.className = "basay-audio-btns";
    wrap.appendChild(makeButton("ipay", text, manualSlug));
    wrap.appendChild(makeButton("hokkien", text, manualSlug));
    // 挿入位置：要素の直後
    el.insertAdjacentElement("afterend", wrap);
    el.dataset.basayAudioBound = "1";
    el.classList.add("basay-has-audio");
  }

  // ─────── ヴォイススイッチャー ───────
  function buildSwitcher(container) {
    if (!container || container.dataset.built === "1") return;
    container.dataset.built = "1";
    container.classList.add("basay-voice-switcher");
    container.innerHTML = `
      <span class="vs-label">🎧 聲線切換</span>
      <button type="button" data-voice="ipay">🔵 IPay</button>
      <button type="button" data-voice="hokkien">🟢 台語</button>
      <span id="basay-voice-status"></span>
      <span class="vs-desc">音源準備中の場合は短い通知が表示されます。</span>
    `;
    container.querySelectorAll("[data-voice]").forEach(b => {
      b.addEventListener("click", () => setVoice(b.dataset.voice));
    });
    setVoice(currentVoice());
  }

  // ─────── 初期化 ───────
  function init() {
    document.querySelectorAll(".basay-voice-switcher-mount").forEach(buildSwitcher);
    document.querySelectorAll("[data-basay]").forEach(attachButtons);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // ─────── 外部公開 API ───────
  window.BasayAudio = { play, slug, setVoice, currentVoice, attachButtons };
})();
