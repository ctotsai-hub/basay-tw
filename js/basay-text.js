// ============================================================
// basay-text.js — 表記 → slug / TTS（v3 / 2026-04-27）
// scripts/basay_text.py と同期。2 音節は [[...,=]] 形式。
// 公開 API: window.BasayText.{ slug, ttsText, derive }
// ============================================================
(function () {
  "use strict";

  const SPECIAL = [
    ["ŋ", "x"], ["Ŋ", "x"], ["ʔ", "x"],
    ["'", "x"], ["’", "x"],
    ["ə", "e"], ["ɨ", "i"],
  ];

  const VOWELS_STR = "aeiouəɨAEIOUƏ";
  function isVowelChar(ch) { return VOWELS_STR.indexOf(ch) >= 0; }

  const DIGRAPHS = [
    "tS", "ts", "TS", "Ts",
    "ng", "NG", "Ng", "nG",
    "ay", "AY", "Ay", "aY",
    "uy", "UY", "Uy", "uY",
    "oy", "OY", "Oy", "oY",
    "ey", "EY", "Ey", "eY",
    "au", "AU", "Au", "aU",
    "ai", "AI", "Ai", "aI",
  ];
  const APOSTROPHES = ["'", "’", "ʔ"];

  // digraph 正規化（eSpeak bsy で y が認識されないため、ay→ai 等へ）
  const DIGRAPH_NORMALIZE = {
    "ay": "ai", "AY": "AI", "Ay": "Ai", "aY": "aI",
    "uy": "ui", "UY": "UI", "Uy": "Ui", "uY": "uI",
    "oy": "oi", "OY": "OI", "Oy": "Oi", "oY": "oI",
    "ey": "ei", "EY": "EI", "Ey": "Ei", "eY": "eI",
  };

  const SUFFIXES = [
    "an","ay","ai","au","na",
    "ku","ik","su","is","ta","it","mi","am","mu","im","ija",
    "aku","isu","ita","ami","imu","ia","ja"
  ].sort((a, b) => b.length - a.length);

  const PARTICLES = new Set(["u", "ta", "nu", "i", "a"]);

  const TRAIL_PUNCT_RE = /[^A-Za-zəɨŋŊ'’ʔ\-]+$/;
  const LEAD_PUNCT_RE = /^[^A-Za-zəɨŋŊ'’ʔ\-]+/;

  function slug(display, manual) {
    if (manual && String(manual).trim()) {
      return String(manual).trim().toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_")
        .replace(/^_+|_+$/g, "");
    }
    let s = String(display || "");
    for (const [src, dst] of SPECIAL) s = s.split(src).join(dst);
    s = s.toLowerCase();
    s = s.replace(/[^a-z0-9]+/g, "_");
    s = s.replace(/^_+|_+$/g, "");
    return s;
  }

  function parseUnits(word) {
    const units = [];
    let i = 0;
    const n = word.length;
    while (i < n) {
      let matched = null;
      for (const dg of DIGRAPHS) {
        if (word.substr(i, dg.length) === dg) { matched = dg; break; }
      }
      if (matched) {
        units.push(DIGRAPH_NORMALIZE[matched] || matched);
        i += matched.length;
        continue;
      }
      const ch = word[i];
      if (APOSTROPHES.indexOf(ch) >= 0) {
        if (units.length > 0 && units[units.length - 1] !== "-") {
          units[units.length - 1] = units[units.length - 1] + "x";
        } else {
          units.push("x");
        }
        i++;
        continue;
      }
      units.push(ch);
      i++;
    }
    return units;
  }

  function isVowelUnit(u) { return u && u.length > 0 && isVowelChar(u[0]); }

  function alphaLower(units) {
    return units.filter(u => u !== "-").join("").toLowerCase();
  }

  function countSyllables(units) {
    let count = 0, inGroup = false;
    for (const u of units) {
      if (u === "-") { inGroup = false; continue; }
      if (isVowelUnit(u)) {
        if (!inGroup) { count++; inGroup = true; }
      } else { inGroup = false; }
    }
    return count;
  }

  function stripOneEndSuffix(alpha) {
    for (const suf of SUFFIXES) {
      if (alpha.length > suf.length && alpha.endsWith(suf)) {
        return [alpha.slice(0, alpha.length - suf.length), suf];
      }
    }
    return null;
  }

  function countUnitsForChars(units, nChars) {
    let total = 0;
    for (let i = units.length - 1; i >= 0; i--) {
      if (units[i] === "-") continue;
      total += units[i].length;
      if (total === nChars) return units.length - i;
      if (total > nChars) return null;
    }
    return total === nChars ? units.length : null;
  }

  function segmentWord(units) {
    const suffixChunks = [];
    let remaining = units.slice();
    while (true) {
      const alpha = alphaLower(remaining);
      const r = stripOneEndSuffix(alpha);
      if (!r) break;
      const [, suf] = r;
      const cnt = countUnitsForChars(remaining, suf.length);
      if (cnt == null || cnt === 0 || cnt >= remaining.length) break;
      suffixChunks.push(remaining.slice(remaining.length - cnt));
      remaining = remaining.slice(0, remaining.length - cnt);
    }
    const segments = [[remaining, "stem"]];
    if (suffixChunks.length > 0) {
      suffixChunks.reverse();
      for (let j = 0; j < suffixChunks.length; j++) {
        const kind = (j === suffixChunks.length - 1) ? "end" : "mid";
        segments.push([suffixChunks[j], kind]);
      }
    }
    return segments;
  }

  function lastNonHyphenUnit(stem, upToIdx) {
    for (let j = upToIdx - 1; j >= 0; j--) {
      if (stem[j] !== "-") return stem[j];
    }
    return "";
  }

  function renderStem(stem) {
    if (stem.length === 0) return "";
    const out = [];
    let foundFirstVowel = false;
    for (let i = 0; i < stem.length; i++) {
      const u = stem[i];
      if (u === "-") {
        out.push(":");
        foundFirstVowel = true;
        continue;
      }
      if (isVowelUnit(u)) {
        if (!foundFirstVowel && i > 0 && !(i === 1 && stem[0] === "-")) {
          out.push(":");
        }
        out.push(u);
        foundFirstVowel = true;
      } else {
        if (foundFirstVowel && out.length > 0 && out[out.length - 1] !== ":") {
          const prev = lastNonHyphenUnit(stem, i);
          if (!isVowelUnit(prev) && !prev.endsWith("x")) {
            out.push(":");
          }
        }
        out.push(u);
      }
    }
    return out.join("");
  }

  function suffixStartsWithVowel(units) {
    for (const u of units) {
      if (u === "-") continue;
      return isVowelUnit(u);
    }
    return false;
  }

  function renderSuffix(suf) {
    if (suf.length === 0) return "";
    if (suffixStartsWithVowel(suf)) {
      return suf.filter(u => u !== "-").join("");
    }
    const out = [];
    let inserted = false;
    for (const u of suf) {
      if (u === "-") continue;
      if (!inserted && isVowelUnit(u)) {
        out.push(":");
        inserted = true;
      }
      out.push(u);
    }
    return out.join("");
  }

  function processSegments(segments) {
    const parts = [];
    for (const [units, kind] of segments) {
      if (kind === "stem") parts.push(renderStem(units));
      else if (kind === "mid") {
        const inner = renderSuffix(units);
        if (suffixStartsWithVowel(units)) parts.push(":" + inner + ":");
        else parts.push(inner + ":");
      } else if (kind === "end") {
        const inner = renderSuffix(units);
        if (suffixStartsWithVowel(units)) parts.push(":" + inner);
        else parts.push(inner);
      }
    }
    let joined = parts.join("");
    while (joined.indexOf("::") >= 0) joined = joined.replace(/::+/g, ":");
    return joined;
  }

  function format2sylBrackets(units) {
    const parts = [];
    let foundFirstVowel = false;
    let prevIsVowel = false;
    for (const u of units) {
      if (u === "-") continue;
      const uLow = u.toLowerCase();
      if (isVowelUnit(u)) {
        if (!foundFirstVowel) {
          if (parts.length > 0) parts.push(":" + uLow);  // 子音 → 最初の母音
          else parts.push(uLow);                          // 母音始まり
        } else {
          parts.push("," + uLow);                         // 母音/子音 → 母音
        }
        foundFirstVowel = true;
        prevIsVowel = true;
      } else {
        if (parts.length === 0) parts.push(uLow);
        else if (prevIsVowel) parts.push("," + uLow);     // 母音 → 子音
        else parts.push(":" + uLow);                       // 連続子音間
        prevIsVowel = false;
      }
    }
    return "[[" + parts.join("") + ",=]]";
  }

  function processToken(token, isFinal) {
    if (!token) return token;
    let lead = "";
    let bare = token;
    let m = bare.match(LEAD_PUNCT_RE);
    if (m) { lead = m[0]; bare = bare.slice(lead.length); }
    let trail = "";
    m = bare.match(TRAIL_PUNCT_RE);
    if (m) { trail = m[0]; bare = bare.slice(0, bare.length - trail.length); }
    if (!bare) return token;

    const units = parseUnits(bare);
    const segments = segmentWord(units);
    let rendered;
    if (countSyllables(units) === 2) {
      rendered = format2sylBrackets(units);
    } else {
      rendered = processSegments(segments);
    }

    const bareAlphaLower = alphaLower(units);
    const hasEndSuffix = segments.length > 0 && segments[segments.length - 1][1] === "end";
    const isParticle = PARTICLES.has(bareAlphaLower);
    const trailHasComma = trail.indexOf(",") >= 0;
    if ((hasEndSuffix || isParticle) && !isFinal && !trailHasComma) {
      if (!rendered.endsWith(",")) rendered += ",";
    }
    return (lead + rendered + trail).toLowerCase();
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
      out.push(processToken(tokens[i], i === n - 1));
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

  window.BasayText = { slug: slug, ttsText: ttsText, derive: derive };
})();
