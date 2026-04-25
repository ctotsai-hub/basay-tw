// ============================================================
// basay-text.js — 表記 → slug / TTS テキスト 派生（JS 側）
// ------------------------------------------------------------
// scripts/basay_text.py と同じ規則を JS で実装したもの。
// 両者は常に同期させること（テストケースを共有）。
//
// 公開 API:
//   window.BasayText.slug(display, manual?)
//   window.BasayText.ttsText(display, manual?)
//   window.BasayText.derive(display, slugOverride?, ttsOverride?)
//
// 仕様サマリ:
//   slug: 小文字化、ŋ/ʔ/' → x、ə → e、ɨ → i、英数字以外 → "_"、両端 strip
//   tts:
//     ① 各ワードが子音始まりなら、最初の母音の直前に ":" 挿入
//        例: paman → p:aman, kwazai → kw:azai, abu → abu (不変)
//     ② "-" → ":"
//     ③ 語末 -ku/-su/-an/-ay/-ai/-ik/-it/-is で ","
//     ④ 助詞 u, ta, a, nu の直後に ","
//     ※ 文末トークンには "," を付けない
// ============================================================

(function () {
  "use strict";

  const SPECIAL = [
    ["ŋ", "x"],
    ["Ŋ", "x"],
    ["ʔ", "x"],
    ["'", "x"],
    ["\u2019", "x"],
    ["ə", "e"],
    ["ɨ", "i"],
  ];

  const VOWELS = "aeiouəɨAEIOUƏ";
  const FINAL_SUFFIXES = ["ku", "su", "an", "ay", "ai", "ik", "it", "is"];
  const PARTICLES = new Set(["u", "ta", "a", "nu"]);

  // 字音文字（特殊含む）以外の trailing 句読点を削るための正規表現
  const TRAIL_PUNCT_RE = /[^A-Za-zəɨŋŊ'\u2019ʔ]+$/;

  function isVowel(ch) {
    return VOWELS.indexOf(ch) >= 0;
  }

  // ─────────────── slug ───────────────
  function slug(display, manual) {
    if (manual && String(manual).trim()) {
      return String(manual)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_")
        .replace(/^_+|_+$/g, "");
    }
    let s = String(display || "");
    for (const [src, dst] of SPECIAL) {
      s = s.split(src).join(dst);
    }
    s = s.toLowerCase();
    s = s.replace(/[^a-z0-9]+/g, "_");
    s = s.replace(/^_+|_+$/g, "");
    return s;
  }

  // ─────────────── TTS ───────────────
  function bareLower(token) {
    return token.replace(TRAIL_PUNCT_RE, "").toLowerCase();
  }

  function wantsTrailingComma(token) {
    const bare = bareLower(token);
    if (!bare) return false;
    if (PARTICLES.has(bare)) return true;
    for (const suf of FINAL_SUFFIXES) {
      if (bare.endsWith(suf)) return true;
    }
    return false;
  }

  // rule ①: 子音始まりなら最初の母音の直前に ":"。母音始まりは変更なし。
  function applyConsonantColon(token) {
    for (let i = 0; i < token.length; i++) {
      if (isVowel(token[i])) {
        if (i === 0) return token;                 // 母音始まり
        if (token[i - 1] === ":") return token;    // 既に直前に ":"
        return token.slice(0, i) + ":" + token.slice(i);
      }
    }
    return token;
  }

  function ttsText(display, manual) {
    if (manual !== undefined && manual !== null && manual !== "") {
      return String(manual);
    }
    const src = String(display || "").trim();
    if (!src) return "";

    const tokens = src.split(/\s+/);
    const n = tokens.length;
    const out = [];

    for (let i = 0; i < n; i++) {
      const tok = tokens[i];
      const wantsComma = wantsTrailingComma(tok);

      // ② "-" → ":"
      let newTok = tok.split("-").join(":");

      // ① 全ワード共通：子音始まりなら最初の母音直前に ":"
      newTok = applyConsonantColon(newTok);

      // ③/④ コンマ（文末を除く）
      if (wantsComma && i < n - 1 && !newTok.endsWith(",")) {
        newTok = newTok + ",";
      }
      out.push(newTok);
    }
    return out.join(" ");
  }

  function derive(display, slugOverride, ttsOverride) {
    return {
      display: display,
      slug: slug(display, slugOverride),
      tts: ttsText(display, ttsOverride),
    };
  }

  // ─────────────── 公開 ───────────────
  window.BasayText = { slug, ttsText, derive };
})();
