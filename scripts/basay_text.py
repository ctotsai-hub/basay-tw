#!/usr/bin/env python3
"""
basay_text.py — 表記から slug と TTS テキストを派生する。

============================================================
設計思想
============================================================
「表記（display form）」を唯一のソースとして、
  ・slug = 音声ファイル名（小文字・英数字・アンダースコアのみ）
  ・tts  = eSpeak-NG の入力テキスト（プロソディマーカー付き）
を機械的に派生させる。手動入力で上書き可能。

============================================================
仕様（2026-04-25 v1）
============================================================

[1] 表記 — 大文字、ハイフン、スペース、正書法すべて保持

[2] slug — 自動変換（手動上書き可）
    a. 特殊文字置換: ŋ→x, Ŋ→x, ʔ→x, '→x, ə→e, ɨ→i
    b. 小文字化
    c. 英数字以外の連続 → "_"
    d. 先頭・末尾の "_" を除去

[3] TTS テキスト — 自動変換（手動上書き可）
    ① 各ワードが子音始まりなら、最初の母音の直前に ":" を挿入。
       母音始まりのワードは変更なし。
       例：paman → p:aman、abu → abu、kwazai → kw:azai
    ② "-" を ":" に置換（音節境界マーカー）
    ③ 語末が次のいずれかなら直後に "," を挿入：
       -ku, -su, -an, -ay, -ai, -ik, -it, -is
    ④ スタンドアロンの u, ta, a, nu の直後に "," を挿入
    ※ 文末トークンには "," を付けない

============================================================
CLI 使用例
============================================================
    python3 basay_text.py "Makawas ita mau Basay"
        → display: Makawas ita mau Basay
        → slug:    makawas_ita_mau_basay
        → tts:     Ma:kawas ita mau Basay

    python3 basay_text.py --test
        → 自己テスト実行
"""
import re
import sys
from typing import Optional


# ─────────────────────── slug ───────────────────────
SPECIAL_CHAR_MAP = {
    'ŋ': 'x',     # 軟口蓋鼻音
    'Ŋ': 'x',
    'ʔ': 'x',     # 声門閉鎖
    "'": 'x',     # アポストロフィ（声門閉鎖）
    '\u2019': 'x', # 右シングルクォート（’）
    'ə': 'e',     # シュワー
    'ɨ': 'i',     # 高中央母音
}


def slug(display: str, manual: Optional[str] = None) -> str:
    """表記 → slug。manual を渡せば上書き。"""
    if manual:
        return re.sub(r'[^a-z0-9_]+', '_', manual.strip().lower()).strip('_')
    s = display or ''
    for src, dst in SPECIAL_CHAR_MAP.items():
        s = s.replace(src, dst)
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = s.strip('_')
    return s


# ─────────────────────── TTS ───────────────────────
VOWELS = set('aeiouəɨAEIOUƏ')

# 語末接尾辞（rule ③）
FINAL_SUFFIXES = ('ku', 'su', 'an', 'ay', 'ai', 'ik', 'it', 'is', 'ta')

# スタンドアロン助詞（rule ④）
PARTICLES = frozenset({'u', 'ta', 'a', 'nu'})

# 字音とみなす文字（特殊文字含む）
LETTER_CHARS = "A-Za-zəɨŋŊ'\u2019ʔ"
_TRAIL_PUNCT_RE = re.compile(rf"[^{LETTER_CHARS}]+$")


def _bare_lower(token: str) -> str:
    """末尾の句読点・記号を除いた字音部を小文字化。"""
    bare = _TRAIL_PUNCT_RE.sub('', token)
    return bare.lower()


def _wants_trailing_comma(token: str) -> bool:
    """rule ③ + rule ④: このトークンの後に "," が必要か？"""
    bare = _bare_lower(token)
    if not bare:
        return False
    if bare in PARTICLES:                  # rule ④
        return True
    for suf in FINAL_SUFFIXES:             # rule ③
        if bare.endswith(suf):
            return True
    return False


def _apply_consonant_colon(token: str) -> str:
    """rule ①：子音始まりのトークンは、最初の母音の直前に ":" を挿入。
    母音始まりのトークンは変更なし。
    例：paman → p:aman, kwazai → kw:azai, abu → abu (不変)。"""
    for i, ch in enumerate(token):
        if ch in VOWELS:
            if i == 0:
                return token              # 母音始まり → 変更なし
            if token[i - 1] == ':':
                return token              # すでに ":" 直後 → 多重挿入防止
            return token[:i] + ':' + token[i:]
    return token                          # 母音なし → 変更なし


def tts_text(display: str, manual: Optional[str] = None) -> str:
    """表記 → eSpeak 入力テキスト。manual を渡せば上書き。"""
    if manual is not None and manual != '':
        return manual
    if not display or not display.strip():
        return ''

    tokens = display.split()
    n = len(tokens)
    out = []

    for i, tok in enumerate(tokens):
        # rule ③/④ の判定はハイフン置換前に実施
        wants_comma = _wants_trailing_comma(tok)

        # rule ② "-" → ":"
        new_tok = tok.replace('-', ':')

        # rule ① 全ワード共通：子音始まりなら最初の母音直前に ":"
        new_tok = _apply_consonant_colon(new_tok)

        # コンマ追加（文末トークンを除く）
        if wants_comma and i < n - 1 and not new_tok.endswith(','):
            new_tok = new_tok + ','

        out.append(new_tok)

    return ' '.join(out)


def derive(display: str,
           slug_override: Optional[str] = None,
           tts_override: Optional[str] = None) -> dict:
    """display から slug, tts を派生（または手動上書き）。"""
    return {
        'display': display,
        'slug': slug(display, slug_override),
        'tts': tts_text(display, tts_override),
    }


# ─────────────────────── 自己テスト ───────────────────────
TEST_CASES = [
    # (display, expected_slug, expected_tts)

    # 子音始まり + 母音始まりの混在
    ("Makawas ita mau Basay",
     "makawas_ita_mau_basay",
     "M:akawas ita m:au B:asay"),

    # 子音始まり、特殊文字含む
    ("kalili'",
     "kalilix",
     "k:alili'"),

    # 末尾接尾辞・助詞 + 全ワード子音始まり
    ("Mani tisu kaman u",
     "mani_tisu_kaman_u",
     "M:ani t:isu, k:aman, u"),

    # ハイフン入り + 母音始まり助詞
    ("Pasika-ik mau na putau a kwazai",
     "pasika_ik_mau_na_putau_a_kwazai",
     "P:asika:ik, m:au n:a p:utau a, kw:azai"),

    # 特殊文字 + 母音始まり助詞
    ("matsaŋasse-na nanom a Tamsuy N'apan",
     "matsaxasse_na_nanom_a_tamsuy_nxapan",
     "m:atsaŋasse:na n:anom a, T:amsuy N':apan"),

    # 母音始まり語（変更なし）+ 子音始まり助詞
    ("Azasa nu zanum-na",
     "azasa_nu_zanum_na",
     "Azasa n:u, z:anum:na"),

    # 母音始まり中央語
    ("Lavi awi-it na",
     "lavi_awi_it_na",
     "L:avi awi:it, n:a"),

    # 子音始まり + 母音始まり混在
    ("kuat isu yaku",
     "kuat_isu_yaku",
     "k:uat isu, y:aku"),

    # 母音始まり 1 語のみ
    ("abu",
     "abu",
     "abu"),

    # 子音始まり 1 語のみ
    ("paman",
     "paman",
     "p:aman"),
]


def run_tests():
    print("basay_text.py self-test")
    print("=" * 64)
    fail = 0
    for display, exp_slug, exp_tts in TEST_CASES:
        d = derive(display)
        s_ok = d['slug'] == exp_slug
        t_ok = d['tts'] == exp_tts
        mark = "✓" if (s_ok and t_ok) else "✗"
        if not (s_ok and t_ok):
            fail += 1
        print(f"[{mark}] IN:   {display!r}")
        print(f"    slug: {d['slug']!r}" + ("" if s_ok else f"   (expected {exp_slug!r})"))
        print(f"    tts:  {d['tts']!r}" + ("" if t_ok else f"   (expected {exp_tts!r})"))
        print()
    print(f"Result: {len(TEST_CASES) - fail}/{len(TEST_CASES)} passed")
    return 0 if fail == 0 else 1


# ─────────────────────── CLI ───────────────────────
def _print_usage():
    print(__doc__, file=sys.stderr)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        _print_usage()
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
    # Plain output for piping: 3 lines
    print(f"display\t{d['display']}")
    print(f"slug\t{d['slug']}")
    print(f"tts\t{d['tts']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
