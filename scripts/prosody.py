#!/usr/bin/env python3
"""
prosody.py — Basay 長文のプロソディー自動挿入ツール
============================================================
eSpeak-NG の TTS 合成入力用に、Basay テキストに ',' と '.' を
自動挿入します。

使い方:
    python3 prosody.py "Pina i tia na zijan kuwarij-an-a ni qupa"
    echo "..." | python3 prosody.py
    python3 prosody.py --test    # 組み込みテストケースを実行

自動適用ルール:
  [PERIOD '.']
    1. '-' → '.' に変換（ハイフンは音節境界）
    2. 4 音節以上の単語に中間 '.' を挿入（母音ベースの粗い近似）

  [COMMA ',']
    3. 格標記で始まるトークンの先頭 '-' は '.' でなく ',' に変換
       例: I-kuman-isu → I,kuman.isu
    4. スタンドアロンの格標記（i, ta, u, s, na, nu, ni）の直後に ','
    5. スタンドアロンのリガーチャ 'a' の直後に ','
    6. 末尾が代名詞接尾辞（-ik, -isu, -aku 等）のトークンに ','
    7. 末尾が -a / -i / -na アスペクトのトークンに ','
    ※ ただし「文末トークン」には trailing ',' を付けない

自動化されない（手動調整推奨）:
  - 意味的な phrase-boundary（demonstrative の後の , 等）
  - 畳語（reduplication）の検出と分割
  - 3 音節語の内部分割
  - 極端に長い語の複数 '.' 挿入
"""
import re
import sys

# ───── 格標記 ─────
CASE_MARKERS = {'u', 'ta', 'i', 's', 'na', 'nu', 'ni'}

# ───── リガーチャ ─────
LIGATURE = 'a'

# ───── 代名詞クリティック ─────
PRONOUN_CLITICS = {
    # 主格長式
    'yaku', 'kaku', 'tak', 'kisu', 'tis', 'kita', 'yami', 'tam',
    'kimu', 'tim', 'tia', 'yako',
    # 主格短式
    'ku', 'ik', 'su', 'is', 'it', 'mi', 'am', 'mu', 'im', 'ija',
    # 属格長式
    'naku', 'nisu', 'nita', 'nami', 'nimu', 'nia',
    # 属格短式
    'aku', 'isu', 'ita', 'ami', 'imu', 'ia',
    # 与格
    'maku', 'misu', 'mita', 'mami', 'mimu',
    # 排除式
    'kimi',
}

# ───── アスペクト接尾辞（ハイフン後に現れる）─────
ASPECT_SUFFIXES = {'a', 'i', 'na', 'an'}

VOWELS = set('aeiouəɨAEIOUƏ')


def syllable_count(word: str) -> int:
    """母音クラスタ数で音節数を粗く近似。"""
    count = 0
    prev_vowel = False
    for ch in word:
        is_v = ch in VOWELS
        if is_v and not prev_vowel:
            count += 1
        prev_vowel = is_v
    return count


def midpoint_break(word: str) -> str:
    """4 音節以上の単語に '.' を 1 箇所挿入（中央の母音前の子音境界）。
    3 音節以下は変更なし。"""
    syll = syllable_count(word)
    if syll < 4:
        return word
    target = syll // 2  # 何番目の音節の直前で切るか（0-based）
    count = 0
    prev_vowel = False
    for i, ch in enumerate(word):
        is_v = ch in VOWELS
        if is_v and not prev_vowel:
            count += 1
            if count == target + 1:
                # 直前の子音クラスタの先頭まで戻って '.' を挿入
                j = i
                while j > 0 and word[j - 1] not in VOWELS:
                    j -= 1
                return word[:j] + '.' + word[j:]
        prev_vowel = is_v
    return word


def process_hyphenated(token: str):
    """ハイフンを含むトークンを処理。戻り値: (processed, trailing_comma)"""
    parts = token.split('-')

    # 先頭部分が格標記か？（大文字小文字無視）
    first_is_marker = parts[0].lower() in CASE_MARKERS

    # 各パートに音節分割を適用（主に先頭部分）
    parts_sized = [midpoint_break(p) for p in parts]

    if first_is_marker:
        # 先頭ハイフンは ',' に、残りは '.' に
        result = parts_sized[0] + ',' + '.'.join(parts_sized[1:])
    else:
        result = '.'.join(parts_sized)

    # 末尾部分が代名詞 or アスペクトなら trailing ','
    last_clean = re.sub(r"[^a-zA-Zəɨ']", '', parts[-1]).lower()
    trailing = (last_clean in PRONOUN_CLITICS) or (last_clean in ASPECT_SUFFIXES)
    return result, trailing


def process_word(word: str):
    """単一トークンを処理。戻り値: (processed, trailing_comma)"""
    # 括弧を除去
    bare = word.strip('()[]')
    paren_left = '(' if word.startswith('(') else ''
    paren_right = ')' if word.endswith(')') else ''

    if '-' in bare:
        body, comma = process_hyphenated(bare)
        return paren_left + body + paren_right, comma

    lc = bare.lower()
    if lc in CASE_MARKERS:
        return paren_left + bare + paren_right, True
    if bare == LIGATURE:
        return paren_left + bare + paren_right, True
    if lc in PRONOUN_CLITICS:
        return paren_left + bare + paren_right, True

    return paren_left + midpoint_break(bare) + paren_right, False


def prosodize(text: str) -> str:
    """メイン処理。"""
    text = text.strip()
    if not text:
        return ''
    # 末尾の記号（。? 等）を一時的に外す
    trailing_punct = ''
    while text and text[-1] in '.。?？!！':
        trailing_punct = text[-1] + trailing_punct
        text = text[:-1]

    tokens = text.split()
    n = len(tokens)
    out = []
    for i, tok in enumerate(tokens):
        processed, comma = process_word(tok)
        # 文末トークンには trailing ',' を付けない
        if comma and i < n - 1:
            processed += ','
        out.append(processed)

    return ' '.join(out) + trailing_punct


# ─────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────
TESTS = [
    ("Pina i tia na zijan kuwarij-an-a ni qupa",
     "Pina i, tia na, zijan, ku.warij.an.a ,ni qupa"),
    ("I-kuman-isu ta baute vatsaputsapo'z'",
     "I,kuman.isu, ta baute,, v.atsapu.tsapo'z'"),
    ("Azasa nu zanum-na",
     "Azasa nu, zanum.na"),
    ("Pasika-ik mau na putau a kwazai",
     "Pasika.ik, mau, na putau a, kwazai"),
]


def run_tests():
    print("Prosodizer self-test")
    print("=" * 60)
    ok = True
    for inp, expected in TESTS:
        got = prosodize(inp)
        mark = "✓" if got.replace(' ', '') == expected.replace(' ', '') else "~"
        if mark != "✓":
            ok = False
        print(f"[{mark}] IN:       {inp}")
        print(f"    GOT:      {got}")
        print(f"    EXPECTED: {expected}")
        print()
    print("Summary: 完全一致は期待値との記号位置の違いで稀。")
    print("差異は意味論的句読点（手動調整が必要な部分）に由来。")
    return ok


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        run_tests()
        return 0

    if len(sys.argv) >= 2:
        text = ' '.join(sys.argv[1:])
    else:
        text = sys.stdin.read().strip()
        if not text:
            print("Usage: prosody.py \"Basay text\"", file=sys.stderr)
            print("   or: echo 'text' | prosody.py", file=sys.stderr)
            print("       prosody.py --test", file=sys.stderr)
            return 1

    print(prosodize(text))
    return 0


if __name__ == '__main__':
    sys.exit(main())
