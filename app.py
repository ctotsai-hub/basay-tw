import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from urllib.parse import quote

import basay_text
import gradio as gr


from blog_post import build_blocks as build_blog_blocks
from blog_post import build_blog_section
ROOT = Path(__file__).resolve().parent
ESPEAK_SRC = ROOT / "espeak-ng"
BUILD_DIR = Path(tempfile.gettempdir()) / "basaytts-build"
ESPEAK_BIN = BUILD_DIR / "src" / "espeak-ng"
DATA_ROOT = ROOT / "basay-data"
BUILD_DATA_ROOT = BUILD_DIR
MAX_CHUNK_CHARS = int(os.environ.get("BASAY_TTS_MAX_CHUNK_CHARS", "450"))
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true"

BUILD_LOCK = threading.Lock()

CUSTOM_CSS = """
/* basay.tw style — always render in light mode regardless of OS preference. */
:root, html, body, .gradio-container { color-scheme: light !important; }
html.dark, body.dark, .gradio-container.dark { color-scheme: light !important; }
:root {
  --color-deep: #1a3a52;
  --color-sand: #f0e6d2;
  --color-algae: #5a7a6b;
  --color-brick: #c86d4a;
  --color-drift: #6b5d54;
  --color-ink: #2c2620;
  --color-mist: #fbf7ef;
  --color-line: rgba(44, 38, 32, 0.12);
  --font-serif: "Noto Serif TC", "Source Han Serif TC", "PingFang TC", "Songti TC", serif;
  --font-sans: "Inter", "Noto Sans TC", "PingFang TC", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", ui-monospace, monospace;
  --max-w: 1080px;
  --radius: 6px;
  --shadow-sm: 0 1px 2px rgba(26, 58, 82, 0.08);
  --shadow-md: 0 6px 24px rgba(26, 58, 82, 0.12);
}
body, .gradio-container {
  background: var(--color-mist) !important;
  color: var(--color-ink) !important;
  font-family: var(--font-serif) !important;
}
.gradio-container {
  max-width: none !important;
  padding: 0 !important;
}
.gradio-container .main,
.gradio-container main.contain {
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}
.gradio-container .block:has(.site-header),
.gradio-container .block:has(.hero),
.gradio-container .block:has(.site-footer),
.gradio-container .html-container:has(.site-header),
.gradio-container .html-container:has(.hero),
.gradio-container .html-container:has(.site-footer),
.gradio-container .prose:has(.site-header),
.gradio-container .prose:has(.hero),
.gradio-container .prose:has(.site-footer) {
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: visible !important;
}
.site-header {
  width: 100%;
  max-width: none;
  background: var(--color-deep) !important;
  color: var(--color-mist) !important;
  border-bottom: 3px solid var(--color-brick) !important;
}
.site-header-inner {
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 1.2rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
}
.brand { display: flex; flex-direction: column; line-height: 1.2; }
.brand a {
  color: var(--color-mist) !important;
  text-decoration: none !important;
  border-bottom: 0 !important;
  font-weight: 600;
}
.brand-main {
  color: var(--color-mist) !important;
  font-size: 1.35rem;
  letter-spacing: .08em;
}
.brand-sub {
  color: var(--color-sand) !important;
  font-size: .85rem;
  font-style: italic;
  opacity: .85;
  margin-top: .2em;
  font-family: var(--font-sans);
}
.site-nav ul {
  list-style: none !important;
  list-style-type: none !important;
  margin: 0 !important;
  padding: 0 !important;
  display: flex;
  gap: .78rem;
  flex-wrap: wrap;
  font-family: var(--font-sans);
  font-size: .98rem;
}
.site-nav li {
  list-style: none !important;
  margin: 0 !important;
  padding: 0 !important;
}
.site-nav li::marker { content: "" !important; }
.site-nav a {
  color: var(--color-mist) !important;
  text-decoration: none !important;
  font-family: var(--font-sans);
  font-size: inherit;
  padding: 0 0 2px;
  border-bottom: 2px solid transparent !important;
}
.site-nav a.active, .site-nav a:hover {
  color: var(--color-sand) !important;
  border-bottom-color: var(--color-brick) !important;
}
.hero {
  width: 100%;
  max-width: none;
  background: linear-gradient(135deg, var(--color-sand) 0%, var(--color-mist) 100%);
  color: var(--color-ink);
  text-align: center;
  padding: 4rem 1.5rem 3.5rem;
  border-bottom: 1px solid var(--color-line);
}
.hero h1 {
  margin: 0 0 .5em;
  font-family: var(--font-serif);
  color: var(--color-deep) !important;
  font-size: 2.8rem;
  line-height: 1.3;
}
.hero .sub {
  color: var(--color-drift) !important;
  font-size: 1.1rem;
  font-style: italic;
  margin: 0;
}
.container {
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 2.5rem 1.5rem 5rem;
}
.intro, .about {
  font-size: 17px;
  line-height: 1.75;
}
.tag {
  display: inline-block;
  background: #efe8d8;
  color: var(--color-deep);
  border: 1px solid #eadfca;
  font-family: var(--font-sans);
  font-size: .78rem;
  padding: .15em .8em;
  border-radius: 12px;
  margin-right: .4em;
  letter-spacing: .04em;
}
.orthography-note {
  margin: .85rem 0 1rem;
  padding: .8rem .9rem;
  background: var(--color-mist);
  border: 1px solid var(--color-line);
  border-left: 4px solid var(--color-algae);
  border-radius: var(--radius);
}
.orthography-note-title {
  margin: 0 0 .55rem;
  color: var(--color-deep);
  font-family: var(--font-sans);
  font-size: .9rem;
  font-weight: 700;
}
.orthography-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
  gap: .4rem .55rem;
}
.orthography-pair {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .4rem;
  padding: .32rem .5rem;
  background: #fff;
  border: 1px solid var(--color-line);
  border-radius: var(--radius);
  color: var(--color-ink);
  font-family: var(--font-mono);
  font-size: .95rem;
}
.orthography-pair span:first-child {
  color: var(--color-deep);
  font-weight: 700;
}
.orthography-pair span:last-child { color: var(--color-drift); }
.section-title h2 {
  font-family: var(--font-serif);
  color: var(--color-deep);
  font-size: 1.6rem;
  border-bottom: 1px solid var(--color-line);
  padding-bottom: .3em;
  margin-top: 2rem;
}
.tts-card {
  background: #fff;
  border: 1px solid var(--color-line);
  border-top: 4px solid var(--color-brick);
  border-radius: var(--radius);
  padding: 1.6rem 1.8rem;
  margin: 1.5rem 0;
  box-shadow: var(--shadow-sm);
}
.tts-card label, .tts-card .label-wrap span {
  font-family: var(--font-sans) !important;
  font-size: .9rem !important;
  color: var(--color-deep) !important;
  font-weight: 600 !important;
}
.tts-card textarea, .tts-card input, .tts-card select {
  font-family: var(--font-mono) !important;
  font-size: 1rem !important;
  background: #fff !important;
  color: var(--color-ink) !important;
  border-color: var(--color-line) !important;
  border-radius: var(--radius) !important;
}
.tts-card textarea {
  background: var(--color-mist) !important;
}
.tts-card button.primary {
  background: var(--color-deep) !important;
  border-color: var(--color-deep) !important;
  color: var(--color-mist) !important;
  font-family: var(--font-sans) !important;
  font-weight: 600 !important;
  letter-spacing: .08em;
  border-radius: var(--radius) !important;
}
.tts-card button.primary:hover {
  background: var(--color-brick) !important;
  border-color: var(--color-brick) !important;
}
.tts-card button.secondary {
  background: var(--color-mist) !important;
  border: 1px solid var(--color-line) !important;
  color: var(--color-deep) !important;
  font-family: var(--font-sans) !important;
  font-weight: 600 !important;
  border-radius: var(--radius) !important;
}
.tts-card button.secondary:hover {
  background: var(--color-sand) !important;
  border-color: var(--color-brick) !important;
}
.tts-card .controls-row {
  align-items: end !important;
  gap: .65rem !important;
}
.tts-card .controls-row > * { min-width: 0 !important; }
.tts-card .controls-row .form { flex: 0 1 auto !important; }
.tts-card .controls-row button {
  min-width: 5.4rem !important;
  height: 2.65rem !important;
  padding: 0 .95rem !important;
}
.tts-card [role="radiogroup"],
.tts-card fieldset .wrap {
  display: flex !important;
  gap: .5rem !important;
  flex-wrap: wrap !important;
}
.tts-card label[data-testid$="radio-label"] {
  border: 1px solid var(--color-line) !important;
  background: var(--color-mist) !important;
  color: var(--color-ink) !important;
  min-width: 5.4rem !important;
  height: 2.65rem !important;
  padding: .45em .9em !important;
  border-radius: var(--radius) !important;
  cursor: pointer !important;
  transition: all .15s ease !important;
  justify-content: center !important;
}
.tts-card label[data-testid$="radio-label"].selected {
  background: var(--color-algae) !important;
  color: var(--color-mist) !important;
  border-color: var(--color-algae) !important;
  box-shadow: 0 0 0 2px rgba(90, 122, 107, .18) !important;
}
.tts-player {
  margin-top: 1rem;
  padding: 1rem;
  background: var(--color-sand);
  border-left: 5px solid var(--color-brick);
  border-radius: var(--radius);
  overflow: visible !important;
}
.tts-player audio {
  display: block;
  width: 100%;
  max-width: 100%;
}
.analysis-page { display: none !important; }
html.basay-debug .main-page { display: none !important; }
html.basay-debug .analysis-page { display: block !important; }
.site-footer {
  width: 100%;
  max-width: none;
  background: var(--color-deep);
  color: var(--color-sand);
  text-align: center;
  padding: 2.5rem 1.5rem 2rem;
  margin-top: 4rem;
  font-family: var(--font-sans);
  font-size: .9rem;
  border-top: 3px solid var(--color-brick);
}
.site-footer a {
  color: var(--color-sand);
  border-bottom: 1px dotted rgba(240, 230, 210, .4);
}
.site-footer a:hover { color: var(--color-mist); }
.site-footer .tagline {
  font-family: var(--font-serif);
  font-style: italic;
  margin-bottom: .8em;
  color: var(--color-mist);
}
footer:not(.site-footer) { display: none !important; }
@media (max-width: 640px) {
  .site-header-inner { flex-direction: column; align-items: flex-start; }
  .site-nav ul { gap: .75rem; }
  .hero { padding: 3rem 1.2rem; }
  .hero h1 { font-size: 2rem; }
  .tts-card .controls-row { align-items: stretch !important; }
}
/* --- daily-updater section (URL path /daily-update or /d) --- */
.daily-updater-page { display: none !important; }
html.basay-daily .main-page { display: none !important; }
html.basay-daily .analysis-page { display: none !important; }
html.basay-daily .daily-updater-page { display: block !important; }
.daily-updater-page .status-box { font-family: var(--font-sans); }
.daily-updater-page .status-box code { font-family: var(--font-mono); }
.daily-updater-page .hint {
  color: var(--color-drift);
  font-family: var(--font-sans);
  font-size: .85rem;
  margin-top: 1rem;
}
"""

HEAD_HTML = """
<script>
(() => {
  const __p = window.location.pathname.replace(/\/+$/, '');
  if (__p === '/fjfllnbius') {
    document.documentElement.classList.add('basay-debug');
  }
  if (__p === '/daily-update' || __p === '/d') {
    document.documentElement.classList.add('basay-daily');
  }
  // Force light theme even when the user's OS prefers dark.
  // Gradio adds 'dark' to <html> / <body> when prefers-color-scheme is dark;
  // strip it on every mutation so basay.tw's light palette stays intact.
  const forceLight = () => {
    const h = document.documentElement;
    if (h.classList.contains('dark')) h.classList.remove('dark');
    if (h.style.colorScheme !== 'light') h.style.colorScheme = 'light';
    const b = document.body;
    if (b) {
      if (b.classList.contains('dark')) b.classList.remove('dark');
      if (b.style.colorScheme !== 'light') b.style.colorScheme = 'light';
    }
  };
  forceLight();
  const __lightObs = new MutationObserver(forceLight);
  const __startObs = () => {
    if (!document.body) { setTimeout(__startObs, 30); return; }
    __lightObs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    __lightObs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  };
  __startObs();
  window.addEventListener('load', forceLight);
  setTimeout(forceLight, 100);
  setTimeout(forceLight, 500);
  setTimeout(forceLight, 1500);
  const hideSpaceBadge = () => {
    const nodes = document.querySelectorAll('a, div, header, section, button');
    for (const node of nodes) {
      const text = (node.textContent || '').replace(/\\s+/g, ' ').trim();
      const rect = node.getBoundingClientRect?.();
      if (
        text.includes('inkuei') &&
        text.includes('basaytts') &&
        rect &&
        rect.top < 120 &&
        rect.right > window.innerWidth * 0.55 &&
        rect.width < 520 &&
        rect.height < 140 &&
        ['fixed', 'absolute', 'sticky'].includes(getComputedStyle(node).position)
      ) {
        node.style.display = 'none';
      }
    }
  };
  window.addEventListener('load', hideSpaceBadge);
  setTimeout(hideSpaceBadge, 500);
  setTimeout(hideSpaceBadge, 1500);
  setTimeout(hideSpaceBadge, 3000);
})();
</script>
"""

HEADER_HTML = """
<header class="site-header">
  <div class="site-header-inner">
    <div class="brand">
      <a href="https://basay.tw/"><span class="brand-main">凱達格蘭 · 巴賽語</span></a>
      <span class="brand-sub">Ketagalan · Basay — 從記憶到再生</span>
    </div>
    <nav class="site-nav">
      <ul>
        <li><a href="https://basay.tw/">首頁</a></li>
        <li><a href="https://basay.tw/grammar/">文法</a></li>
        <li><a href="https://basay.tw/education/">教育推進</a></li>
        <li><a href="https://basay.tw/research/">研究成果</a></li>
        <li><a href="https://basay.tw/blog/">研究筆記</a></li>
        <li><a href="https://inkuei-basaytts.hf.space/" class="active">語音合成</a></li>
        <li><a href="https://basay.tw/dictionary/">辭典</a></li>
      </ul>
    </nav>
  </div>
</header>
<section class="hero">
  <h1>巴賽語語音合成</h1>
  <p class="sub">Basay Speech Synthesis ⸺ IPay 歷史復原・台語適配 兩種音色</p>
</section>
"""

INTRO_HTML = """
<section class="intro">
  <p>
    本頁基於 <strong>eSpeak-NG</strong> 自製音聲定義（<code>Ipay</code> / <code>Lobanov</code>），可將
    巴賽語表記轉為語音。目前提供兩種音色：
  </p>
  <p>
    <span class="tag">IPay 歷史復原</span>
    <span class="tag">台語適配（Lobanov）</span>
  </p>
</section>
"""

ORTHOGRAPHY_HTML = """
<section class="orthography-note">
  <p class="orthography-note-title">正書法対照表</p>
  <div class="orthography-grid">
    <div class="orthography-pair"><span>ŋ</span><span>n'</span></div>
    <div class="orthography-pair"><span>ʃ</span><span>s'</span></div>
    <div class="orthography-pair"><span>ɭ</span><span>l'</span></div>
    <div class="orthography-pair"><span>ɮ</span><span>z'</span></div>
    <div class="orthography-pair"><span>ə</span><span>o'</span></div>
  </div>
</section>
"""

ABOUT_HTML = """
<section class="about">
  <h2>關於本服務</h2>
  <p>
    本語音合成服務基於 <a href="https://github.com/espeak-ng/espeak-ng">eSpeak-NG</a> 自定義語音定義。
    <code>bsy</code>（IPay 歷史復原）以 19 世紀末文獻記載的音值為依據；
    <code>bsystd</code>（台語適配）則以現代台語音色為基礎，套用 Lobanov 正規化以接近 Basay 音域。
  </p>
  <p>
    技術說明與規則文檔詳見 <a href="https://basay.tw/research/">研究成果</a>。
  </p>
  <p><a href="https://basay.tw/">← 回到 basay.tw 首頁</a></p>
</section>
"""

FOOTER_HTML = """
<footer class="site-footer">
  <div class="tagline">Makawas ita mau Basay ⸺ 大家一起說巴賽語。</div>
  <div>
    © 2026 basay.tw ｜
    <a href="https://basay.tw/about/">關於</a> ｜
    <a href="https://github.com/ctotsai-hub/basay-tw">GitHub</a> ｜
    內容採 CC BY-NC-SA 4.0 授權
  </div>
</footer>
"""

APOSTROPHE_VARIANTS = str.maketrans({
    "‘": "'",
    "’": "'",
    "ʻ": "'",
    "ʼ": "'",
    "＇": "'",
    "`": "'",
})

PRENASAL_TOKENS = ("n'", "nx", "ng", "ŋ")

PHONEME_TOKENS = (
    # n' / nx / ng are handled as a short geminate n.  The previous N mapping
    # made the following vowel carry too much nasal tail in connected speech.
    ("n'", "nn"),
    ("nx", "nn"),
    ("ng", "nn"),
    ("ŋ", "nn"),
    ("l'", "l_"),
    ("lx", "l_"),
    ("ɭ", "l_"),
    ("z'", "Z"),
    ("zx", "Z"),
    ("ɮ", "Z"),
    ("s'", "S"),
    ("sx", "S"),
    ("ʃ", "S"),
    ("o'", "@"),
    ("ox", "@"),
    ("ts", "ts"),
)

SAFE_PHONEME_TOKENS = (
    ("n'", ("n", "n")),
    ("nx", ("n", "n")),
    ("ng", ("n", "n")),
    ("ŋ", ("n", "n")),
    ("l'", ("l_",)),
    ("lx", ("l_",)),
    ("ɭ", ("l_",)),
    ("z'", ("Z",)),
    ("zx", ("Z",)),
    ("ɮ", ("Z",)),
    ("s'", ("S",)),
    ("sx", ("S",)),
    ("ʃ", ("S",)),
    ("o'", ("@",)),
    ("ox", ("@",)),
    ("ts", ("t", "s")),
    ("ay", ("ai",)),
    ("uy", ("ui",)),
    ("oy", ("oi",)),
    ("ey", ("ei",)),
)

PHONEME_CHARS = {
    "a": "a",
    "e": "e",
    "i": "i",
    "o": "o",
    "u": "u",
    "ə": "@",
    "@": "@",
    "p": "p",
    "q": "q",
    "b": "b",
    "k": "k",
    "m": "m",
    "h": "h",
    "v": "v",
    "r": "r",
    "w": "w",
    "y": "j",
    "j": "j",
    "g": "q",
    "n": "n",
    "l": "l",
    "z": "z",
    "s": "s",
    "t": "t",
    ".": "_p",
    "?": "_q",
    "!": "_e",
}

PHONEME_VOWELS = {"a", "e", "i", "o", "u", "@"}
WORD_RE = re.compile(r"[A-Za-zŋɭɮʃəƏɨƗ'`’‘ʼʻ＇-]+")
EMBEDDED_PHONEMES_RE = re.compile(r"(\[\[.*?\]\])")
SPACE_RE = re.compile(r"[ \t]+")
CHUNK_BOUNDARY_RE = re.compile(r"(?<=[。．.!?！？;；:：,\n])\s+")


def normalize_display_text(text):
    text = (text or "").translate(APOSTROPHE_VARIANTS)
    text = text.replace("ʔ", "'").replace("ɨ", "i").replace("Ɨ", "I")
    text = text.replace("Ə", "ə")
    text = text.replace("，", ", ").replace("、", ", ")
    text = text.replace("。", ". ").replace("．", ". ")
    text = text.replace("！", "! ").replace("？", "? ")
    text = SPACE_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def word_to_phonemes(word):
    word = (
        word.translate(APOSTROPHE_VARIANTS)
        .replace("Ə", "@")
        .replace("ə", "@")
        .replace("ɨ", "i")
        .replace("Ɨ", "I")
    )
    lowered = word.lower()
    phonemes = []
    index = 0
    while index < len(word):
        for source, target in PHONEME_TOKENS:
            if lowered.startswith(source, index):
                phonemes.append(target)
                index += len(source)
                break
        else:
            if word[index] == "N":
                target = "N"
            else:
                target = PHONEME_CHARS.get(lowered[index])
            if target:
                phonemes.append(target)
            index += 1

    for i, phoneme in enumerate(phonemes):
        if phoneme not in PHONEME_VOWELS:
            continue
        phonemes[i] = "'" + phoneme
        break

    return "".join(phonemes)


def word_to_safe_phonemes(word):
    word = (
        word.translate(APOSTROPHE_VARIANTS)
        .replace("Ə", "@")
        .replace("ə", "@")
        .replace("ɨ", "i")
        .replace("Ɨ", "I")
    )
    lowered = word.lower()
    phonemes = []
    index = 0
    while index < len(word):
        for source, target in SAFE_PHONEME_TOKENS:
            if lowered.startswith(source, index):
                phonemes.extend(target)
                index += len(source)
                break
        else:
            if word[index] == "N":
                target = "N"
            else:
                target = PHONEME_CHARS.get(lowered[index])
            if target:
                phonemes.append(target)
            index += 1
    return phonemes


def word_to_tts_text(word):
    word = normalize_display_text(word)
    lowered = word.lower()
    out = []
    index = 0
    while index < len(word):
        for source in PRENASAL_TOKENS:
            if lowered.startswith(source, index):
                out.append("nn")
                index += len(source)
                break
        else:
            ch = word[index]
            if ch == "ŋ":
                out.append("nn")
            elif ch == "Ə":
                out.append("ə")
            elif ch == "ɨ":
                out.append("i")
            elif ch == "Ɨ":
                out.append("I")
            else:
                out.append(ch)
            index += 1
    return "".join(out)


def has_prenasal_token(word):
    lowered = word.translate(APOSTROPHE_VARIANTS).lower()
    return any(token in lowered for token in PRENASAL_TOKENS)


def normalize_embedded_phonemes(text):
    def replace_block(match):
        inner = match.group(0)[2:-2]
        return f"[[{inner.replace('y', 'j').replace('Y', 'j')}]]"

    return EMBEDDED_PHONEMES_RE.sub(replace_block, text)


def normalize_text(text):
    return normalize_embedded_phonemes(basay_text.tts_text(normalize_display_text(text)))


def debug_word_analysis(text):
    rows = []
    parts = EMBEDDED_PHONEMES_RE.split(text)
    for part in parts:
        if part.startswith("[[") and part.endswith("]]"):
            rows.append(f"{part} -> {part}")
            continue
        for match in WORD_RE.finditer(part):
            word = match.group(0)
            tts = normalize_embedded_phonemes(basay_text.tts_text(word))
            marker = " (ng/n'/nx -> nn)" if has_prenasal_token(word) else ""
            rows.append(f"{word} -> {tts}{marker}")
    return "\n".join(rows)


def split_long_text(text, max_chars=MAX_CHUNK_CHARS):
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    current = ""
    for match in re.finditer(r"\S+\s*", text):
        token = match.group(0)
        stripped = token.strip()
        if not stripped:
            continue
        candidate = current + token
        if current and len(candidate.strip()) > max_chars:
            chunks.append(current.strip())
            current = token
        else:
            current = candidate

        while len(current.strip()) > max_chars:
            split_at = current.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            chunks.append(current[:split_at].strip())
            current = current[split_at:].strip()
    if current:
        chunks.append(current)
    return chunks


def run(cmd, cwd=None, env=None):
    try:
        subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, flush=True)
        raise RuntimeError(exc.stdout or str(exc)) from exc


def ensure_built():
    if ESPEAK_BIN.exists() and (BUILD_DIR / "espeak-ng-data" / "phondata").exists():
        return

    with BUILD_LOCK:
        if ESPEAK_BIN.exists() and (BUILD_DIR / "espeak-ng-data" / "phondata").exists():
            return

        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        run(
            [
                "cmake",
                "-S",
                str(ESPEAK_SRC),
                "-B",
                str(BUILD_DIR),
                "-DUSE_LIBPCAUDIO=OFF",
                "-DENABLE_TESTS=OFF",
            ]
        )
        run(["cmake", "--build", str(BUILD_DIR), "--target", "data"])


def concatenate_wavs(inputs, output):
    if len(inputs) == 1:
        shutil.copyfile(inputs[0], output)
        return

    params = None
    frames = []
    silence_frames = None
    for wav_path in inputs:
        with wave.open(str(wav_path), "rb") as src:
            if params is None:
                params = src.getparams()
                silence = bytes(params.sampwidth * params.nchannels)
                silence_frames = silence * int(params.framerate * 0.08)
            elif src.getparams()[:3] != params[:3]:
                raise RuntimeError("Cannot concatenate WAV files with different formats.")
            frames.append(src.readframes(src.getnframes()))

    with wave.open(str(output), "wb") as dst:
        dst.setparams(params)
        for i, frame_data in enumerate(frames):
            if i and silence_frames:
                dst.writeframes(silence_frames)
            dst.writeframes(frame_data)


def normalize_audio(wav_path):
    # Keep Space synthesis robust; loudness normalization can be enabled later
    # after the core Basay conversion is stable.
    return
    if os.environ.get("BASAY_NO_NORMALIZE") == "1":
        return
    if shutil.which("ffmpeg") is None:
        return
    tmp = Path(wav_path).with_suffix(".norm.wav")
    try:
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-af",
                LOUDNORM_FILTER,
                str(tmp),
            ]
        )
        tmp.replace(wav_path)
    except subprocess.CalledProcessError as exc:
        print(f"Audio normalization skipped: {exc}", flush=True)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def synthesize_audio(voice_id, phoneme_text, output, env):
    chunks = split_long_text(phoneme_text)
    with tempfile.TemporaryDirectory(prefix="basaytts-chunks.") as tmpdir:
        tmpdir = Path(tmpdir)
        chunk_wavs = []
        for i, chunk in enumerate(chunks):
            chunk_wav = tmpdir / f"chunk-{i:03d}.wav"
            run([str(ESPEAK_BIN), "-v", voice_id, "-a", "200", "-w", str(chunk_wav), chunk], env=env)
            chunk_wavs.append(chunk_wav)
        concatenate_wavs(chunk_wavs, output)
    normalize_audio(output)


def resolve_voice_id(voice):
    voice_text = str(voice or "").lower()
    if "std" in voice_text or "台" in voice_text or "hokkien" in voice_text:
        return "tai/bsystd"
    return "tai/bsy"


def audio_player_html(wav_path):
    file_url = "/gradio_api/file=" + quote(str(Path(wav_path)))
    return (
        '<div class="tts-player">'
        f'<audio controls src="{file_url}"></audio>'
        "</div>"
    )


def synthesize(text, voice):
    display_text = normalize_display_text(text)
    phoneme_text = normalize_text(display_text)
    if not phoneme_text:
        raise gr.Error("Please enter text.")

    ensure_built()

    voice_id = resolve_voice_id(voice)
    out = tempfile.NamedTemporaryFile(prefix=f"{voice}.", suffix=".wav", delete=False)
    out.close()

    env = os.environ.copy()
    env["ESPEAK_DATA_PATH"] = str(BUILD_DATA_ROOT)
    synthesize_audio(voice_id, phoneme_text, out.name, env)
    return audio_player_html(out.name)


def synth_to_wav(text, voice_short, tts_override=None):
    """Daily Updater 用: 表記 + voice short name -> wav bytes.
    `tts_override` を渡せば basay_text の派生をバイパスし、その文字列を
    そのまま eSpeak に渡す（OPERATIONS.md の data-tts 上書きに相当）。
    """
    if tts_override:
        phoneme_text = normalize_embedded_phonemes(tts_override)
    else:
        display_text = normalize_display_text(text)
        phoneme_text = normalize_text(display_text)
    if not phoneme_text:
        raise ValueError("Empty input")

    ensure_built()

    voice_id = resolve_voice_id(voice_short)
    out = tempfile.NamedTemporaryFile(
        prefix=f"{voice_short}_daily_", suffix=".wav", delete=False)
    out.close()
    try:
        env = os.environ.copy()
        env["ESPEAK_DATA_PATH"] = str(BUILD_DATA_ROOT)
        synthesize_audio(voice_id, phoneme_text, out.name, env)
        return Path(out.name).read_bytes()
    finally:
        Path(out.name).unlink(missing_ok=True)


def synth_to_wav_file(tts_text: str, voice_short: str) -> str:
    """dict_build_audio.py 用 API エンドポイント。
    tts_text は basay_text 変換済みの文字列。tts_override で二重変換を防ぐ。
    WAV ファイルパスを返す。
    """
    wav_bytes = synth_to_wav("", voice_short, tts_override=tts_text)
    out = tempfile.NamedTemporaryFile(
        prefix=f"{voice_short}_api_", suffix=".wav", delete=False)
    out.write(wav_bytes)
    out.close()
    return out.name


def clear_inputs():
    return "", ""


def analyze_text(text):
    display_text = normalize_display_text(text)
    phoneme_text = normalize_text(display_text)
    return (
        display_text,
        phoneme_text,
        debug_word_analysis(display_text),
        "\n".join(split_long_text(phoneme_text)) if phoneme_text else "",
    )


with gr.Blocks(title="巴賽語語音合成 — basay.tw", css=CUSTOM_CSS, head=HEAD_HTML) as demo:
    gr.HTML(HEADER_HTML)
    with gr.Column(elem_classes=["container", "main-page"]):
        gr.HTML(INTRO_HTML)
        gr.Markdown("## 輸入文字 ⸺ Synthesize", elem_classes=["section-title"])
        with gr.Group(elem_classes=["tts-card"]):
            text = gr.Textbox(
                label="巴賽語表記",
                value="",
                placeholder="例：Makawas ita mau Basay",
                lines=5,
            )
            gr.HTML(ORTHOGRAPHY_HTML)
            with gr.Row(elem_classes=["controls-row"]):
                voice = gr.Radio(
                    choices=[("Ipay", "bsy"), ("台語", "bsystd")],
                    value="bsy",
                    show_label=False,
                )
                speak = gr.Button("合成", variant="primary")
                clear = gr.Button("削除", variant="secondary")
            audio = gr.HTML()

        gr.HTML("<hr>")
        gr.HTML(ABOUT_HTML)
    with gr.Column(elem_classes=["container", "analysis-page"]):
        gr.Markdown("## 解析確認 ⸺ Analysis", elem_classes=["section-title"])
        with gr.Group(elem_classes=["tts-card"]):
            analysis_input = gr.Textbox(
                label="巴賽語表記",
                value="",
                placeholder="例：vutsusa / tina / Makawas ita mau Basay",
                lines=5,
            )
            analyze = gr.Button("解析 Analyze", variant="primary")
            normalized_out = gr.Textbox(label="Normalized input", lines=3)
            tts_out = gr.Textbox(label="eSpeak input", lines=4)
            words_out = gr.Textbox(label="Word analysis", lines=8)
            chunks_out = gr.Textbox(label="Chunks", lines=6)

    # --- Daily Updater section (hidden unless URL path is /daily-update) ---
    from daily_updater import build_daily_section  # noqa: E402
    build_daily_section(synth_to_wav)
    build_blog_section()

    # --- dict_build_audio.py 用 API エンドポイント ---
    with gr.Row(visible=False):
        _api_text = gr.Textbox()
        _api_voice = gr.Textbox()
        _api_wav = gr.File()
    gr.Button(visible=False).click(
        synth_to_wav_file,
        inputs=[_api_text, _api_voice],
        outputs=[_api_wav],
        api_name="synth_wav",
    )

    gr.HTML(FOOTER_HTML)

    speak.click(synthesize, inputs=[text, voice], outputs=[audio])
    clear.click(clear_inputs, outputs=[text, audio])
    analyze.click(
        analyze_text,
        inputs=[analysis_input],
        outputs=[normalized_out, tts_out, words_out, chunks_out],
    )


if __name__ == "__main__":
    demo.launch(show_error=True, allowed_paths=[str(Path(tempfile.gettempdir()))])
