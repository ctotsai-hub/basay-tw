#!/usr/bin/env python3
"""
basay_text.py — 表記から slug と TTS テキストを派生する（v3.2 / 2026-05-31 unified）

HF Space と GitHub `scripts/` の共通版。両者の機能を統合：

  ・接尾辞 longest-match (A/B/C 三層) ＋ 辞書(D) を 4 番目の層として参加
      A: -an -ay -ai -au -na -,            (2026/05/16: -i, -a 削除)
      B: -ku -ik -su -is -ta -it -mi -am -mu -im -ia -ja  (-ia/-ja は C から移動)
      C: -aku -isu -ita -ami -imu -ija -eja               (-ija/-eja を追加整理)
      D: WORD_REWRITE_OVERRIDES (data/word_rewrites.tsv) — 完全一致のみ採用
  ・D fallback: A/B/C どれも一致しない時、末尾 1〜3 文字を仮想接尾辞として
      剥がし、残りが D にあれば採用（D 未登録なら絶対に剥がさない）
  ・空白入り D target: top-level の bare full match のときに再トークン化
  ・音韻ルール: 母音 + b → 母音 + pb （TTS 専用、slug 不変）

  ・slug: ŋ/Ŋ/ʔ/'/' → x、ə → e、ɨ → i、英数字以外 → "_"、両端 strip
  ・TTS 補足:
      ⑧ ' / ' / ʔ → x（直前子音の複製）
      ① 各ワード最初の子音単位の直後に :
      ② 語中の連続子音（粘着 x の後ろは除く）の間に :
      ④ - を : に置換
      ⑤ 語末接尾辞: 直前の母音の前に :、文末以外は , を付加
      ⑥ 語中接尾辞: 前後に :
      ⑦ 助詞 u/ta/nu/i/a/na の後（文末除く）に ,
      ⑨ 2 音節語は [[...,=]] 形式で出力
"""
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

SPECIAL_CHAR_MAP = {
    'ŋ': 'x', 'Ŋ': 'x', 'ʔ': 'x',
    "'": 'x', '’': 'x',
    'ə': 'e', 'ɨ': 'i',
}


# --- word_rewrites.tsv (HF Space と同じ仕組み) -----------------------
# Format:  source<TAB>target  (タブ区切り推奨、スペース区切りも許容)
#   source は小文字に正規化されてマッチ（case-insensitive）
#   target にスペースが含まれていたら、結果が re-tokenize される
# 配置: scripts/data/word_rewrites.tsv （リポジトリ管理、HF Space と同期）
_BASAY_TEXT_DIR = Path(__file__).resolve().parent
WORD_REWRITE_PATH = _BASAY_TEXT_DIR / 'data' / 'word_rewrites.tsv'


def load_word_rewrites(path=WORD_REWRITE_PATH):
    """Load TAB-separated source→target rewrites. Returns dict[str, str].
    Source keys are lowercased. Empty / commented (#) lines are skipped.
    """
    rewrites = {}
    if not path.exists():
        return rewrites
    for line_no, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '\t' in line:
            source, target = line.split('\t', 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError(
                    f'{path}:{line_no}: expected SOURCE<TAB>TARGET (got {line!r})'
                )
            source, target = parts
        source = source.strip().lower()
        target = target.strip()
        if not source or not target:
            raise ValueError(
                f'{path}:{line_no}: source and target must be non-empty'
            )
        rewrites[source] = target
    return rewrites


WORD_REWRITE_OVERRIDES = load_word_rewrites()


_NG_AS_APOS_RE = re.compile(r'([nN])[gG]')


def slug(display, manual=None):
    if manual:
        return re.sub(r'[^a-z0-9_]+', '_', manual.strip().lower()).strip('_')
    s = display or ''
    # 本ユーザ orthography では `ng` は n' (preglottalized n) の入力バリ。
    # n'azi / nxazi / ngazi が同じ slug `nxazi` になるよう統一しておく。
    s = _NG_AS_APOS_RE.sub(lambda m: m.group(1) + 'x', s)
    for src, dst in SPECIAL_CHAR_MAP.items():
        s = s.replace(src, dst)
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


VOWELS = set('aeiouəɨAEIOUƏ')
DIGRAPHS = (
    'tS', 'ts', 'TS', 'Ts',
    # 注意: ng/NG/Ng/nG は本ユーザの orthography では n' (preglottalized n) の
    # 入力バリエーションとして使われるため、digraph として扱わず _parse_units
    # の特殊処理 (cons + 'g'/'x'/apostrophe → 子音複製) に流す。
    'ay', 'AY', 'Ay', 'aY',
    'uy', 'UY', 'Uy', 'uY',
    'oy', 'OY', 'Oy', 'oY',
    'ey', 'EY', 'Ey', 'eY',
    'au', 'AU', 'Au', 'aU',
    'ai', 'AI', 'Ai', 'aI',
)
APOSTROPHES = ("'", '’', 'ʔ')

# 2026/05/16: 'A' から 'i','a' 取り消し、'B' に 'ia','ja' 移動、
# 'C' から 'ia','ja' を取り、'ija','eja' を追加
SUFFIX_GROUPS = {
    'A': ['an', 'ay', 'ai', 'au', 'na', ','],
    'B': ['ku', 'ik', 'su', 'is', 'ta', 'it', 'mi', 'am', 'mu', 'im', 'ia', 'ja'],
    'C': ['aku', 'isu', 'ita', 'ami', 'imu', 'ija', 'eja'],
}
ALL_SUFFIXES_SORTED = sorted(
    set(SUFFIX_GROUPS['A'] + SUFFIX_GROUPS['B'] + SUFFIX_GROUPS['C']),
    key=len, reverse=True
)
PARTICLES = frozenset({'u', 'ta', 'nu', 'i', 'a', 'na'})


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
        # apostrophe または直入力 'x'/'g' (slug/別綴り 形) は
        # 「直前子音の複製」として処理する。これにより:
        #   n'apan / nxapan / ngapan → ['n','n','a','p','a','n']
        #     → [[n:n:a,p,a,n,=]]
        # bsy で bracket 内 n+: + n+: + a... のパターンが geminate と等価に
        # 機能する（PC 検証済み）。母音直後の apostrophe は従来通り 'x' 後置。
        # 'x' は n/l/s/z の後 (slug 形)、'g' は n の後のみ (本ユーザ orthography)。
        is_cons_apostrophe = (
            (ch in APOSTROPHES) or
            (ch.lower() == 'x' and units and units[-1] != '-'
             and len(units[-1]) == 1 and units[-1].lower() in 'nlsz') or
            (ch.lower() == 'g' and units and units[-1] != '-'
             and len(units[-1]) == 1 and units[-1].lower() == 'n')
        )
        if is_cons_apostrophe:
            if units and units[-1] != '-':
                last = units[-1]
                if _is_vowel_unit(last):
                    # vowel + ' (kalili' 等) は従来通り 'x' 後置
                    units[-1] = last + 'x'
                else:
                    # consonant + ' / consonant + 'x' は子音複製
                    units.append(last)
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


def _count_consonant_units(units):
    return sum(1 for u in units if u != '-' and not _is_vowel_unit(u))


def _segment_word(units):
    """A/B/C 三層 longest-match に加え、辞書(D)を 4 番目の層として参加させる.

    各反復で:
      1) 残り bare 全体が WORD_REWRITE_OVERRIDES に完全一致 → target に置換、
         書き換えを 1 回適用したフラグを立てて続行（無限ループ防止）
      2) A/B/C 接尾辞剥がし → 適用、次反復へ
      3) A/B/C どれにも一致しない時、末尾 1〜3 文字を仮想接尾辞として
         剥がしてみて、残りが D に登録されていれば採用する（D fallback）
      4) 全部失敗 → 終了

    安全 break（全子音残り）の手前で次反復の D 救済可能性を peek し、
    D 登録があれば剥がしを続ける（例：vks→vuks）。
    target に空白が含まれる場合は _process_token 側で再トークン化する
    （top-level の full bare match のときのみ発生）。
    """
    suffix_chunks = []
    remaining = units[:]
    rewrite_applied = False
    while True:
        alpha = _alpha_lower(remaining)
        # --- Tier D: 完全一致 ---
        if not rewrite_applied and alpha in WORD_REWRITE_OVERRIDES:
            target = WORD_REWRITE_OVERRIDES[alpha]
            if ' ' not in target:
                # 音韻ルールは _process_token 側でも適用されるが、
                # D target にも一応適用しておく（V+b → V+pb 等の保険）
                target = _apply_phonological_rules(target)
                remaining = _parse_units(target)
                rewrite_applied = True
                continue
            # 空白入り target はここでは扱わず通常処理へフォールスルー
        # --- Tier A/B/C: longest-match suffix stripping ---
        result = _strip_one_end_suffix(alpha)
        if result is None:
            # --- D fallback: A/B/C 不一致時、末尾 1〜3 文字を仮想接尾辞として
            # 剥がし、残りが D にあれば採用。D 未登録なら絶対に剥がさない。
            matched_fallback = False
            for k in (1, 2, 3):
                cnt_fb = _count_units_for_chars(remaining, k)
                if cnt_fb is None or cnt_fb == 0 or cnt_fb >= len(remaining):
                    continue
                cand_alpha = _alpha_lower(remaining[:-cnt_fb])
                if cand_alpha in WORD_REWRITE_OVERRIDES:
                    suffix_chunks.append(remaining[-cnt_fb:])
                    remaining = remaining[:-cnt_fb]
                    matched_fallback = True
                    break
            if not matched_fallback:
                break
            continue
        _, suf = result
        cnt = _count_units_for_chars(remaining, len(suf))
        if cnt is None or cnt == 0 or cnt >= len(remaining):
            break
        next_remaining = remaining[:-cnt]
        # 安全：全子音残りなら通常 break、ただし D が救済可能なら続行
        if _count_syllables(next_remaining) == 0 and _count_consonant_units(next_remaining) > 1:
            if _alpha_lower(next_remaining) not in WORD_REWRITE_OVERRIDES:
                break
        suffix_chunks.append(remaining[-cnt:])
        remaining = next_remaining
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


def _process_token(token, is_final, _depth=0):
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

    # --- top-level D lookup with space-target handling ---
    # bare 全体が D ヒット & target に空白あり → 複数トークンに分割再帰
    full_match = WORD_REWRITE_OVERRIDES.get(bare.lower())
    if full_match and ' ' in full_match and _depth < 3:
        sub_tokens = full_match.split()
        n = len(sub_tokens)
        rendered_pieces = []
        for i, sub in enumerate(sub_tokens):
            this_lead = lead if i == 0 else ''
            this_trail = trail if i == n - 1 else ''
            sub_is_final = is_final and (i == n - 1)
            piece = _process_token(this_lead + sub + this_trail,
                                   is_final=sub_is_final, _depth=_depth + 1)
            rendered_pieces.append(piece)
        return ' '.join(rendered_pieces)

    tts_bare = full_match if full_match else bare
    # 音韻ルール（tts_bare に対して、後段の解析前に適用）
    tts_bare = _apply_phonological_rules(tts_bare)
    units = _parse_units(tts_bare)
    segments = _segment_word(units)
    # 2 音節判定は D 書き換え後の stem ＋ 剥がした接尾辞で再構築
    units_after = []
    for seg_units, _kind in segments:
        units_after.extend(seg_units)
    if _count_syllables(units_after) == 2:
        rendered = _format_2syl_brackets(units_after)
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


# --- 音韻ルール（TTS 専用前処理：slug は変更しない） -----------------
# 母音の直後にくる /b/ を /pb/ として発音させる。
# 例: kubaban → kupbapban,  abu → apbu,  aba → apba
# (語頭の /b/ は変換しない。"batu" → "batu" のまま)
# 必要に応じて他の voiced 子音にも拡張可能：
#   - /v/: vapvan, lapve のパターン
#   - /d/ /g/ /z/ など
_VOWEL_PB_RE = re.compile(r'([aeiouAEIOU])([bB])')

def _apply_phonological_rules(text):
    """TTS 入力テキストに音韻ルールを適用して返す。

    現在のルール:
      1. 母音 + b  →  母音 + pb   （kubaban → kupbapban）

    slug 派生には影響させないため、tts_text の中だけで使う。
    """
    if not text:
        return text
    # rule 1: /b/ after vowel → /pb/
    text = _VOWEL_PB_RE.sub(r'\1p\2', text)
    return text


def tts_text(display, manual=None):
    if manual is not None and manual != '':
        return manual
    if not display or not display.strip():
        return ''
    # 注：D（word_rewrites）と音韻ルールは _process_token 内で適用される。
    #     ここでは単純にトークン化して各トークンを処理するだけ。
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
    ("abu",       "abu",       "[[a,p:b,u,=]]"),  # V+b → V+pb 適用
    ("paman",     "paman",     "[[p:a,m,a,n,=]]"),
    ("kuman",     "kuman",     "[[k:u,m,a,n,=]]"),
    ("paslin",    "paslin",    "[[p:a,s:l,i,n,=]]"),
    ("palsu",     "palsu",     "[[p:a,l:s,u,=]]"),
    # n' / nx (slug 形) は子音複製で 2 つの n unit にする → bracket 内で n:n になる
    # 例: [[n:n:a,p,a,n,=]] が geminate + final stress を両立させる
    ("n'apan",    "nxapan",    "[[n:n:a,p,a,n,=]]"),
    # 多語フレーズ
    ("paman tisu",
     "paman_tisu",
     "[[p:a,m,a,n,=]], [[t:i,s,u,=]]"),
    ("Makawas ita mau Basay",
     "makawas_ita_mau_basay",
     "m:akawas [[i,t,a,=]], m:au, [[b:a,s,ai,=]]"),
    # === v3.1: D-as-4th-tier longest-match + 音韻 V+b ===
    ("lave",            "lave",            "[[l:a,p:v,e,=]]"),
    ("vkas",            "vkas",            "[[v:u,k,a,s,=]]"),
    ("vkasan",          "vkasan",          "v:ukas:an"),
    ("wanak",           "wanak",           "[[u,a,n,a,k,=]]"),
    ("wanakka",         "wanakka",         "uanak:k:a"),  # D fallback: -a 仮想剥がし
    ("knaul\'ijan",      "knaulxijan",      "kn:au [[l:l:i,j,a,n,=]]"),
    ("kubaban",         "kubaban",         "k:up:bap:b:an"),  # V+b 2 か所
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
