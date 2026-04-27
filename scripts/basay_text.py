#!/usr/bin/env python3
"""
basay_text.py — 表記から slug と TTS テキストを派生する（v3 / 2026-04-27）

仕様サマリ:
  ・slug: ŋ/Ŋ/ʔ/'/' → x、ə → e、ɨ → i、英数字以外 → "_"、両端 strip
  ・TTS:
      ⑧ ' / ' / ʔ → x（直前文字に粘着）
      ① 各ワード最初の子音単位の直後に :
      ② 語中の連続子音（粘着 x の後ろは除く）の間に :
      ④ - を : に置換
      ⑤ 語末接尾辞: 直前の母音の前に :、文末以外は , を付加
      ⑥ 語中接尾辞: 前後に :
      ⑦ 助詞 u/ta/nu/i/a の後（文末除く）に ,
      ⑨ 2 音節語は [[...,=]] 形式で出力
  ・接尾辞 longest-match (内側へ反復):
      A: -an -ay -ai -au -na
      B: -ku -ik -su -is -ta -it -mi -am -mu -im -ija
      C: -aku -isu -ita -ami -imu -ia -ja
"""
import re
import sys
from typing import List, Optional, Tuple

SPECIAL_CHAR_MAP = {
    'ŋ': 'x', 'Ŋ': 'x', 'ʔ': 'x',
    "'": 'x', '’': 'x',
    'ə': 'e', 'ɨ': 'i',
}


def slug(display, manual=None):
    if manual:
        return re.sub(r'[^a-z0-9_]+', '_', manual.strip().lower()).strip('_')
    s = display or ''
    for src, dst in SPECIAL_CHAR_MAP.items():
        s = s.replace(src, dst)
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


VOWELS = set('aeiouəɨAEIOUƏ')
DIGRAPHS = (
    'tS', 'ts', 'TS', 'Ts',
    'ng', 'NG', 'Ng', 'nG',
    'ay', 'AY', 'Ay', 'aY',
    'uy', 'UY', 'Uy', 'uY',
    'oy', 'OY', 'Oy', 'oY',
    'ey', 'EY', 'Ey', 'eY',
    'au', 'AU', 'Au', 'aU',
    'ai', 'AI', 'Ai', 'aI',
)
APOSTROPHES = ("'", '’', 'ʔ')

SUFFIX_GROUPS = {
    'A': ['an', 'ay', 'ai', 'au', 'na'],
    'B': ['ku', 'ik', 'su', 'is', 'ta', 'it', 'mi', 'am', 'mu', 'im', 'ija'],
    'C': ['aku', 'isu', 'ita', 'ami', 'imu', 'ia', 'ja'],
}
ALL_SUFFIXES_SORTED = sorted(
    set(SUFFIX_GROUPS['A'] + SUFFIX_GROUPS['B'] + SUFFIX_GROUPS['C']),
    key=len, reverse=True
)
PARTICLES = frozenset({'u', 'ta', 'nu', 'i', 'a'})


# digraph 正規化（eSpeak bsy で y が認識されないため、ay→ai 等へ写像）
DIGRAPH_NORMALIZE = {
    'ay': 'ai', 'AY': 'AI', 'Ay': 'Ai', 'aY': 'aI',
    'uy': 'ui', 'UY': 'UI', 'Uy': 'Ui', 'uY': 'uI',
    'oy': 'oi', 'OY': 'OI', 'Oy': 'Oi', 'oY': 'oI',
    'ey': 'ei', 'EY': 'EI', 'Ey': 'Ei', 'eY': 'eI',
}


def _parse_units(word):
    units = []
    i, n = 0, len(word)
    while i < n:
        matched = None
        for dg in DIGRAPHS:
            if word.startswith(dg, i):
                matched = dg
                break
        if matched:
            units.append(DIGRAPH_NORMALIZE.get(matched, matched))
            i += len(matched)
            continue
        ch = word[i]
        if ch in APOSTROPHES:
            if units and units[-1] != '-':
                units[-1] = units[-1] + 'x'
            else:
                units.append('x')
            i += 1
            continue
        units.append(ch)
        i += 1
    return units


def _is_vowel_unit(u):
    return bool(u) and u[0] in VOWELS


def _alpha_lower(units):
    return ''.join(u for u in units if u != '-').lower()


def _count_syllables(units):
    count = 0
    in_group = False
    for u in units:
        if u == '-':
            in_group = False
            continue
        if _is_vowel_unit(u):
            if not in_group:
                count += 1
                in_group = True
        else:
            in_group = False
    return count


def _strip_one_end_suffix(alpha):
    for suf in ALL_SUFFIXES_SORTED:
        if len(alpha) > len(suf) and alpha.endswith(suf):
            return alpha[:-len(suf)], suf
    return None


def _count_units_for_chars(units, n_chars):
    total = 0
    for i in range(len(units) - 1, -1, -1):
        if units[i] == '-':
            continue
        total += len(units[i])
        if total == n_chars:
            return len(units) - i
        if total > n_chars:
            return None
    return None if total != n_chars else len(units)


def _segment_word(units):
    suffix_chunks = []
    remaining = units[:]
    while True:
        alpha = _alpha_lower(remaining)
        result = _strip_one_end_suffix(alpha)
        if result is None:
            break
        _, suf = result
        cnt = _count_units_for_chars(remaining, len(suf))
        if cnt is None or cnt == 0 or cnt >= len(remaining):
            break
        suffix_chunks.append(remaining[-cnt:])
        remaining = remaining[:-cnt]
    segments = [(remaining, 'stem')]
    if suffix_chunks:
        suffix_chunks.reverse()
        for j, chunk in enumerate(suffix_chunks):
            kind = 'end' if j == len(suffix_chunks) - 1 else 'mid'
            segments.append((chunk, kind))
    return segments


def _last_unit(stem, up_to_idx):
    for j in range(up_to_idx - 1, -1, -1):
        if stem[j] != '-':
            return stem[j]
    return ''


def _render_stem(stem):
    if not stem:
        return ''
    out = []
    found_first_vowel = False
    for i, u in enumerate(stem):
        if u == '-':
            out.append(':')
            found_first_vowel = True
            continue
        if _is_vowel_unit(u):
            if not found_first_vowel and i > 0 and not (i == 1 and stem[0] == '-'):
                out.append(':')
            out.append(u)
            found_first_vowel = True
        else:
            if found_first_vowel and out and out[-1] != ':':
                prev = _last_unit(stem, i)
                if not _is_vowel_unit(prev) and not prev.endswith('x'):
                    out.append(':')
            out.append(u)
    return ''.join(out)


def _suffix_starts_with_vowel(units):
    for u in units:
        if u == '-':
            continue
        return _is_vowel_unit(u)
    return False


def _render_suffix(suf):
    if not suf:
        return ''
    if _suffix_starts_with_vowel(suf):
        return ''.join(u for u in suf if u != '-')
    out = []
    inserted = False
    for u in suf:
        if u == '-':
            continue
        if not inserted and _is_vowel_unit(u):
            out.append(':')
            inserted = True
        out.append(u)
    return ''.join(out)


def _process_segments(segments):
    parts = []
    for units, kind in segments:
        if kind == 'stem':
            parts.append(_render_stem(units))
        elif kind == 'mid':
            inner = _render_suffix(units)
            if _suffix_starts_with_vowel(units):
                parts.append(':' + inner + ':')
            else:
                parts.append(inner + ':')
        elif kind == 'end':
            inner = _render_suffix(units)
            if _suffix_starts_with_vowel(units):
                parts.append(':' + inner)
            else:
                parts.append(inner)
    joined = ''.join(parts)
    while '::' in joined:
        joined = joined.replace('::', ':')
    return joined


def _format_2syl_brackets(units):
    """rule ⑨：2 音節語は [[ phonemes,= ]] 形式（全て小文字）。
    分離ルール:
      ・先頭子音群 → 最初の母音: :
      ・母音 → 子音: ,
      ・連続子音間: :
      ・子音 → 母音 / 母音 → 母音: ,
    例：paman → [[p:a,m,a,n,=]]
        palsu → [[p:a,l:s,u,=]]（語中 ls クラスタ）
        ita   → [[i,t,a,=]]、abu → [[a,b,u,=]]"""
    parts = []
    found_first_vowel = False
    prev_is_vowel = False
    for u in units:
        if u == '-':
            continue
        u_low = u.lower()
        if _is_vowel_unit(u):
            if not found_first_vowel:
                if parts:
                    parts.append(':' + u_low)  # 子音 → 最初の母音
                else:
                    parts.append(u_low)        # 母音始まり
            else:
                parts.append(',' + u_low)      # 母音 → 母音 or 子音 → 母音
            found_first_vowel = True
            prev_is_vowel = True
        else:
            if not parts:
                parts.append(u_low)
            elif prev_is_vowel:
                parts.append(',' + u_low)      # 母音 → 子音
            else:
                parts.append(':' + u_low)      # 連続子音間
            prev_is_vowel = False
    return '[[' + ''.join(parts) + ',=]]'


_TRAIL_PUNCT_RE = re.compile(r"[^A-Za-zəɨŋŊ'’ʔ\-]+$")
_LEAD_PUNCT_RE = re.compile(r"^[^A-Za-zəɨŋŊ'’ʔ\-]+")


def _process_token(token, is_final):
    if not token:
        return token
    lead = ''
    bare = token
    m = _LEAD_PUNCT_RE.match(bare)
    if m:
        lead = m.group(0)
        bare = bare[len(lead):]
    trail = ''
    m = _TRAIL_PUNCT_RE.search(bare)
    if m:
        trail = m.group(0)
        bare = bare[:-len(trail)]
    if not bare:
        return token

    units = _parse_units(bare)
    segments = _segment_word(units)
    if _count_syllables(units) == 2:
        rendered = _format_2syl_brackets(units)
    else:
        rendered = _process_segments(segments)

    bare_alpha_lower = _alpha_lower(units)
    has_end_suffix = bool(segments and segments[-1][1] == 'end')
    is_particle = bare_alpha_lower in PARTICLES
    trail_has_comma = ',' in trail
    if (has_end_suffix or is_particle) and not is_final and not trail_has_comma:
        if not rendered.endswith(','):
            rendered = rendered + ','
    # TTS 全体を小文字化（eSpeak で大文字が音素名と衝突するため）
    return (lead + rendered + trail).lower()


def tts_text(display, manual=None):
    if manual is not None and manual != '':
        return manual
    if not display or not display.strip():
        return ''
    tokens = display.split()
    n = len(tokens)
    out = []
    for i, tok in enumerate(tokens):
        out.append(_process_token(tok, is_final=(i == n - 1)))
    return ' '.join(out)


def derive(display, slug_override=None, tts_override=None):
    return {
        'display': display,
        'slug': slug(display, slug_override),
        'tts': tts_text(display, tts_override),
    }


TEST_CASES = [
    # 1 音節 / 3+ 音節：bracket 不使用、出力小文字
    ("Makawas",   "makawas",   "m:akawas"),
    ("mau",       "mau",       "m:au"),
    ("tsu",       "tsu",       "ts:u"),
    ("amaku",     "amaku",     "am:aku"),
    ("kumanisu",  "kumanisu",  "k:um:an:isu"),
    ("kalili'",   "kalilix",   "k:alilix"),
    # 2 音節：bracket [[..,=]]（diphthong ay/au/ai 1 ユニット、連続子音は :）
    ("ita",       "ita",       "[[i,t,a,=]]"),
    ("Basay",     "basay",     "[[b:a,s,ai,=]]"),
    ("lusa",      "lusa",      "[[l:u,s,a,=]]"),
    ("zanum",     "zanum",     "[[z:a,n,u,m,=]]"),
    ("batu",      "batu",      "[[b:a,t,u,=]]"),
    ("abu",       "abu",       "[[a,b,u,=]]"),
    ("paman",     "paman",     "[[p:a,m,a,n,=]]"),
    ("kuman",     "kuman",     "[[k:u,m,a,n,=]]"),
    ("paslin",    "paslin",    "[[p:a,s:l,i,n,=]]"),
    ("palsu",     "palsu",     "[[p:a,l:s,u,=]]"),
    ("n'apan",    "nxapan",    "[[nx:a,p,a,n,=]]"),
    # 多語フレーズ
    ("paman tisu",
     "paman_tisu",
     "[[p:a,m,a,n,=]], [[t:i,s,u,=]]"),
    ("Makawas ita mau Basay",
     "makawas_ita_mau_basay",
     "m:akawas [[i,t,a,=]], m:au, [[b:a,s,ai,=]]"),
]


def run_tests():
    print("basay_text.py self-test (v3, [[ ]] accent)")
    print("=" * 64)
    fail = 0
    for display, exp_slug, exp_tts in TEST_CASES:
        d = derive(display)
        s_ok = d['slug'] == exp_slug
        t_ok = d['tts'] == exp_tts
        mark = "OK" if (s_ok and t_ok) else "NG"
        if not (s_ok and t_ok):
            fail += 1
        print("[" + mark + "] " + repr(display))
        if not s_ok:
            print("    slug got " + repr(d['slug']) + " expected " + repr(exp_slug))
        if not t_ok:
            print("    tts  got " + repr(d['tts']) + " expected " + repr(exp_tts))
    print("Result: " + str(len(TEST_CASES) - fail) + "/" + str(len(TEST_CASES)) + " passed")
    return 0 if fail == 0 else 1


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__, file=sys.stderr)
        return 0
    if args[0] == '--test':
        return run_tests()
    slug_override = None
    tts_override = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--slug' and i + 1 < len(args):
            slug_override = args[i + 1]
            i += 2
            continue
        if a == '--tts' and i + 1 < len(args):
            tts_override = args[i + 1]
            i += 2
            continue
        rest.append(a)
        i += 1
    text = ' '.join(rest)
    d = derive(text, slug_override, tts_override)
    print("display\t" + d['display'])
    print("slug\t" + d['slug'])
    print("tts\t" + d['tts'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
