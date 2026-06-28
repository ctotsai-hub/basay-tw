"""
Basay / Traditional Chinese ASR — faster-whisper + 辞書支援
HuggingFace Spaces 対応 Gradio アプリ（完全無料）

辞書支援:
  - initial_prompt に Basay 語彙を自動注入して認識精度を向上
  - 転写結果を辞書でルックアップして意味を表示
"""

from __future__ import annotations

import json
import re
from difflib import get_close_matches
from pathlib import Path

import gradio as gr
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).parent
DICT_JSONL  = BASE_DIR / "dictionary" / "basay_dict.jsonl"
DICT_JSON   = BASE_DIR / "dictionary" / "dictionary.json"
SYLLABLE_MD = BASE_DIR / "syllable" / "basay_syllable_inventory.md"
CONFIG_DIR  = BASE_DIR / "config"
RULES_CFG   = CONFIG_DIR / "rules.txt"
ALTS_CFG    = CONFIG_DIR / "alts.txt"

# ---------------------------------------------------------------------------
# 音節目録ロード・音節境界解析
# ---------------------------------------------------------------------------

def _load_syllables(md_path: Path) -> set[str]:
    """basay_syllable_inventory.md から有効音節セットを抽出する。"""
    syllables: set[str] = set()
    if not md_path.exists():
        print("[ASR] 音節ファイルが見つかりません。")
        return syllables
    for line in md_path.read_text(encoding="utf-8").splitlines():
        # | ba | ba | ★ | 形式の表行をパース
        if not line.startswith("| "):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        syl = parts[1].strip().lower()
        if syl and syl != "正書法" and not syl.startswith("'"):
            syllables.add(syl)
    print(f"[ASR] 音節目録ロード完了: {len(syllables)} 音節")
    return syllables


def _segment(word: str, syllables: set[str]) -> list[str] | None:
    """
    動的計画法で単語を有効な Basay 音節列に分割する。
    スコア = 音節長の二乗和を最大化 → CVC（長音節）を CV より優先。
      例: tan·a (3²+1²=10) > ta·na (2²+2²=8)
    同スコアのタイは >= で後勝ち（j が大きい = 現在音節が短い = 前側が長い）にすることで
    左優先最長マッチを実現する。
      例: mam·ay·u·la (9+4+1+4=18) > ma·may·u·la (4+9+1+4=18) ← 同スコアだが前が長い
    完全分割できない場合は None を返す。
    """
    w = word.lower()
    n = len(w)

    # dp[i] = (score, prev_j)  score=-1 は未到達
    dp: list[tuple[int, int | None]] = [(-1, None)] * (n + 1)
    dp[0] = (0, -1)

    for i in range(1, n + 1):
        for j in range(max(0, i - 7), i):
            if dp[j][0] < 0:
                continue
            syl = w[j:i]
            if syl in syllables:
                new_score = dp[j][0] + (i - j) ** 2
                if new_score > dp[i][0]:
                    dp[i] = (new_score, j)

    if dp[n][0] < 0:
        return None

    result: list[str] = []
    pos = n
    while pos > 0:
        _, prev = dp[pos]
        result.append(w[prev:pos])  # type: ignore[arg-type]
        pos = prev  # type: ignore[assignment]
    return list(reversed(result))


def _analyze_syllables(text: str, syllables: set[str]) -> str:
    """
    転写テキストの各語を音節境界解析し、結果を返す。
    ✅ 完全分割可  ⚠️ 部分分割  ❓ 分割不可
    """
    if not syllables or not text.strip():
        return ""

    words = re.findall(r"[a-zA-Z']+", text)
    lines: list[str] = []

    for word in words:
        segs = _segment(word, syllables)
        if segs:
            lines.append(f"✅ {word} → {' · '.join(segs)}")
        else:
            # 部分的に分割できる箇所を探す（先頭から貪欲）
            w = word.lower()
            partial: list[str] = []
            pos = 0
            while pos < len(w):
                matched = False
                for length in range(min(7, len(w) - pos), 0, -1):
                    chunk = w[pos:pos + length]
                    if chunk in syllables:
                        partial.append(chunk)
                        pos += length
                        matched = True
                        break
                if not matched:
                    partial.append(f"[{w[pos]}]")  # 未知文字
                    pos += 1
            lines.append(f"❓ {word} → {' · '.join(partial)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 辞書ロード
# ---------------------------------------------------------------------------

def _load_dictionary() -> tuple[dict[str, list[str]], str]:
    """
    辞書を読み込み、(word→zh訳リスト, initial_prompt文字列) を返す。
    ファイルがなければ空で返す。
    """
    word_map: dict[str, list[str]] = {}

    src = DICT_JSONL if DICT_JSONL.exists() else (DICT_JSON if DICT_JSON.exists() else None)
    if src is None:
        print("[ASR] 辞書ファイルが見つかりません。辞書支援なしで動作します。")
        return word_map, ""

    try:
        if src.suffix == ".jsonl":
            lines = src.read_text(encoding="utf-8").splitlines()
            entries = [json.loads(l) for l in lines if l.strip()]
        else:
            entries = json.loads(src.read_text(encoding="utf-8"))

        for e in entries:
            raw = e.get("basay", "")
            # バリアント（| 区切り）は最初の形のみ使用
            word = raw.split("|")[0].strip()
            # 接頭辞マーカー（-）・空・長すぎる語を除外
            if not word or word.startswith("-") or len(word) > 15:
                continue
            zh = e.get("zh", [])
            if word not in word_map:
                word_map[word] = zh

        print(f"[ASR] 辞書ロード完了: {len(word_map)} 語")
    except Exception as ex:
        print(f"[ASR] 辞書ロードエラー: {ex}")

    prompt = _build_prompt(word_map)
    return word_map, prompt


def _build_prompt(word_map: dict[str, list[str]], max_chars: int = 800) -> str:
    """
    Whisper の initial_prompt 用文字列を生成。

    方針:
    - ts/ts' 始まりの語を除外（zh モード由来の ts バイアスを避ける）
    - t・m・ma・ta 系の語を先頭に置き、t が破裂音であることを Whisper に示す
    - 残りを語長昇順で詰める
    """
    if not word_map:
        return ""

    def is_valid(w: str) -> bool:
        return (
            2 <= len(w) <= 12
            and " " not in w
            and bool(re.match(r"^[a-zA-Z']+$", w))
            and not w.startswith("ts")
            and not w.startswith("ts'")
        )

    candidates = [w for w in word_map if is_valid(w)]

    # b 始まりを最優先（b→p 誤認バイアスを打ち消す）
    b_words  = sorted([w for w in candidates if w.startswith(("ba","bi","bu","be","bo","bun","bai","bau"))], key=len)
    # v 始まり（有声音の存在を示す）
    v_words  = sorted([w for w in candidates if w.startswith(("va","vi","vu","ve","vo","van"))], key=len)
    # au/ai 二重母音を含む語（diphthong パターンの提示）
    au_words = sorted([w for w in candidates if "au" in w or "ai" in w or "au" in w], key=len)[:15]
    # 残り
    others   = sorted([w for w in candidates
                       if w not in set(b_words) and w not in set(v_words) and w not in set(au_words)],
                      key=len)

    # 辞書に存在する頻出語を先頭に固定。yaku を3回繰り返してマレー語名バイアスを打ち消す
    core = [w for w in ["basay", "yaku", "yaku", "yaku", "auina", "mata", "ina", "ta", "na", "ka", "si", "nu"]
            if w in word_map or w == "yaku"]

    ordered = core + [w for w in b_words + v_words + au_words + others if w not in set(core)]
    prompt = "Basay: "
    for w in ordered:
        addition = w + ", "
        if len(prompt) + len(addition) > max_chars:
            break
        prompt += addition

    return prompt.rstrip(", ")


# ---------------------------------------------------------------------------
# mi モード音素曖昧性：マオリ語出力音素 → 起こりうる Basay 音素リスト
# 1対多マッピングのため、全候補を辞書で検索して複数表示する
# ---------------------------------------------------------------------------
PHONEME_ALTS: list[tuple[str, list[str]]] = [
    # (Maori出力, Basay候補リスト)  ― 長いパターン優先
    ("tsu", ["tsu"]),
    ("tu",  ["tsu", "tu"]),
    ("wh",  ["v", "w"]),
    ("wa",  ["ma", "pa", "va", "wa"]),
    ("wi",  ["mi", "pi", "vi", "wi"]),
    ("wu",  ["mu", "pu", "vu", "wu"]),
    ("wo",  ["mo", "po", "vo", "wo"]),
    ("w",   ["m", "p", "v", "w"]),
    ("f",   ["v", "f"]),
    ("j",   ["ts", "t", "j"]),
    ("p",   ["v", "p"]),
    ("k",   ["q", "k"]),
    ("q",   ["p", "q"]),
]

# UI テキストボックス表示用デフォルト値
# 形式: Maori出力 → Basay候補1 / 候補2 / ...
DEFAULT_ALTS_TEXT = """\
tsu → tsu
tu → tsu / tu
wh → v / w
wa → ma / pa / va / wa
wi → mi / pi / vi / wi
wu → mu / pu / vu / wu
wo → mo / po / vo / wo
w → m / p / v / w
f → v / f
j → ts / t / j
p → v / p
k → q / k
q → p / q\
"""


def _alts_from_text(text: str) -> list[tuple[str, list[str]]]:
    """
    テキストボックスの内容から PHONEME_ALTS 形式のリストを生成する。
    形式: Maori出力 → 候補1 / 候補2 / ...  （# 以降はコメント）
    """
    result: list[tuple[str, list[str]]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].strip()
        if not line or "→" not in line:
            continue
        src, rest = line.split("→", 1)
        src = src.strip()
        dsts = [d.strip() for d in rest.split("/") if d.strip()]
        if src and dsts:
            result.append((src, dsts))
    return result or PHONEME_ALTS


def _expand_candidates(word: str, alts: list[tuple[str, list[str]]] | None = None, depth: int = 2) -> list[str]:
    """
    Maori 音素の代替候補を BFS で最大 depth 段階展開する。
    depth=2 で k→q + q→p のような2段階変換（kumniqa→qumnipa）を捕捉できる。
    """
    active_alts = alts if alts is not None else PHONEME_ALTS
    w = word.lower()
    candidates: dict[str, None] = {w: None}
    frontier: set[str] = {w}

    for _ in range(depth):
        next_frontier: set[str] = set()
        for current in frontier:
            for src, dsts in active_alts:
                if src not in current:
                    continue
                for dst in dsts:
                    if dst == src:
                        continue
                    replaced = current.replace(src, dst, 1)  # 最初の出現のみ
                    if replaced not in candidates:
                        candidates[replaced] = None
                        next_frontier.add(replaced)
        frontier = next_frontier
        if not frontier:
            break

    return list(candidates.keys())


# ---------------------------------------------------------------------------
# Basay 語境界回復（辞書最大マッチング）
# ---------------------------------------------------------------------------

def _segment_words(text: str, word_map: dict[str, list[str]], syllables: set[str]) -> str:
    """
    融合した語トークンを辞書と音節目録を使い最大マッチングで分割する。
    既にスペースで区切られているトークンはそのまま通し、
    辞書にないトークンのみ分割を試みる。
    最長一致（前進）: 辞書ヒット優先、次に音節境界優先。
    """
    tokens = text.split()
    result: list[str] = []

    for tok in tokens:
        w = tok.lower()

        # CJK文字・非ラテン文字を含むトークンは分割しない
        if any(0x3000 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF for c in tok):
            result.append(tok)
            continue

        # ハイフン区切りの多音節トークン（中国語拼音など）は分割しない
        if "-" in tok and all(part.isascii() for part in tok.split("-")):
            result.append(tok)
            continue

        # すでに辞書にある or 短い → そのまま
        if w in word_map or len(w) <= 4:
            result.append(tok)
            continue

        # 最大マッチングで分割を試みる
        segments = _max_match_split(w, word_map, syllables)
        if segments and len(segments) > 1:
            result.extend(segments)
        else:
            result.append(tok)

    return " ".join(result)


_SUFFIX_A_CHARS = ("i", "a")  # A クラス接尾辞（1文字）


def _max_match_split(w: str, word_map: dict[str, list[str]], syllables: set[str]) -> list[str]:
    """
    前進最大マッチング: 辞書語（4文字以上）> 音節分割可能な部分 の順で貪欲に切る。
    辞書語の直後が A クラス接尾辞（-i / -a）の場合は吸収して 1 トークンにまとめる。
    例: kuman + i → kumani（-i は次トークンの頭に漏れない）
    """
    pos = 0
    parts: list[str] = []
    max_len = min(len(w), 15)

    while pos < len(w):
        best_len = 0
        dict_hit = False

        # 辞書ヒットを優先（4文字以上・長い順）
        for end in range(min(pos + max_len, len(w)), pos + 3, -1):
            chunk = w[pos:end]
            if chunk in word_map:
                best_len = end - pos
                dict_hit = True
                break

        # 辞書ヒット後: 直後が A クラス接尾辞なら吸収（-i / -a）
        if dict_hit:
            next_pos = pos + best_len
            if next_pos < len(w) and w[next_pos] in _SUFFIX_A_CHARS:
                # 接尾辞を付けた形も辞書にある or 音節分割可なら吸収
                extended = w[pos:next_pos + 1]
                if extended in word_map or _segment(extended, syllables) is not None:
                    best_len += 1  # -i / -a を吸収

        # 辞書ミスの場合、音節分割できる最長チャンクを選ぶ
        if best_len == 0:
            for end in range(min(pos + max_len, len(w)), pos + 1, -1):
                chunk = w[pos:end]
                if _segment(chunk, syllables) is not None:
                    best_len = end - pos
                    break

        if best_len == 0:
            best_len = 1  # 最終手段

        parts.append(w[pos:pos + best_len])
        pos += best_len

    return parts


# ---------------------------------------------------------------------------
# Basay 形態素解析（子詞・フォーカス接辞の剥離）
# ---------------------------------------------------------------------------
# 子詞クラス（動詞の右側に付着、D→C→B→A の順で外側から）
_MORPH_D = ["na"]
_MORPH_C = ["aku", "isu", "ita", "ami", "imu", "ija", "eja",  # 長い順に並べる
            "ku", "ik", "su", "is", "ta", "it", "mi", "am", "mu", "im", "ia", "ja",
            "n'"]  # ŋ 鼻音接尾辞（n' は声門鼻音、単独分離を防ぐ）
_MORPH_B = ["an", "ay", "ai", "au"]
_MORPH_A = ["i", "a"]

_VOWELS = set("aeiou")


def _strip_one(w: str, suffixes: list[str], min_root: int = 2) -> list[str]:
    """suffixes のうち末尾に一致するものを剥離した候補リストを返す（元形も含む）。"""
    results = [w]
    for suf in suffixes:
        if w.endswith(suf) and len(w) - len(suf) >= min_root:
            results.append(w[:-len(suf)])
    return results


def _strip_suffixes(word: str) -> list[str]:
    """D→C→B→A の順に子詞を剥離し、各段階のルート候補を全列挙する。"""
    roots: set[str] = set()
    w = word.lower()

    for wd in _strip_one(w, _MORPH_D):
        for wc in _strip_one(wd, _MORPH_C):
            for wb in _strip_one(wc, _MORPH_B):
                for wa in _strip_one(wb, _MORPH_A):
                    if wa != w:
                        roots.add(wa)
                if wb != w:
                    roots.add(wb)
            if wc != w:
                roots.add(wc)
        if wd != w:
            roots.add(wd)

    return list(roots)


def _strip_focus(word: str) -> list[str]:
    """
    フォーカス接辞を剥離してルート候補を返す。
    - <um> インフィックス: C-um-V... → CV...（例: s-um-emmam → semmam）
    - m(a)- プリフィックス: ma+... → ...（例: semamman → semman）
    """
    w = word.lower()
    candidates: list[str] = []

    # ma- / m- プリフィックス
    if w.startswith("ma") and len(w) > 3:
        candidates.append(w[2:])
    if w.startswith("m") and len(w) > 2 and w[1] not in _VOWELS:
        candidates.append(w[1:])
    # i- プリフィックス（対象フォーカス）
    if w.startswith("i") and len(w) > 2 and w[1] not in _VOWELS:
        candidates.append(w[1:])

    # <um> インフィックス: 語頭子音の直後に "um"
    if len(w) > 3 and w[0] not in _VOWELS and w[1:3] == "um":
        candidates.append(w[0] + w[3:])
    # 語頭が "um" の場合（母音始まり語根）
    if w.startswith("um") and len(w) > 2:
        candidates.append(w[2:])

    return candidates


def _morph_lookup(word: str, word_map: dict[str, list[str]]) -> tuple[str | None, str | None]:
    """
    形態素解析でルートを特定し (root, meaning) を返す。見つからなければ (None, None)。
    優先順: フォーカス剥離 → 子詞剥離 → 組み合わせ。
    """
    w = word.lower()

    def hit(root: str) -> tuple[str, str] | None:
        if root in word_map and word_map[root]:
            return root, ' / '.join(word_map[root])
        return None

    # フォーカス剥離のみ
    for r in _strip_focus(w):
        if (h := hit(r)):
            return h
        # フォーカス剥離 → 子詞剥離
        for r2 in _strip_suffixes(r):
            if (h := hit(r2)):
                return h

    # 子詞剥離のみ
    for r in _strip_suffixes(w):
        if (h := hit(r)):
            return h
        # 子詞剥離 → フォーカス剥離
        for r2 in _strip_focus(r):
            if (h := hit(r2)):
                return h

    return None, None


def _lookup(text: str, word_map: dict[str, list[str]], alts: list[tuple[str, list[str]]] | None = None) -> str:
    """
    転写テキストの各トークンを辞書でルックアップ。
    ① 音素展開（完全一致）→ ② 形態素解析（子詞・フォーカス剥離）→ ③ 近似一致
    """
    if not word_map or not text:
        return ""

    tokens = re.findall(r"[a-zA-Z']+", text)
    lines = []
    seen: set[str] = set()

    for tok in tokens:
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)

        # ① 音素展開で全候補を辞書検索（完全一致も候補に含む）
        candidates = _expand_candidates(key, alts)
        hits: list[str] = []
        for cand in candidates:
            if cand in word_map and word_map[cand]:
                meaning = ' / '.join(word_map[cand])
                hits.append(f"{cand}（{meaning}）")

        if hits:
            if len(hits) == 1 and key in word_map:
                lines.append(f"**{tok}** → {' / '.join(word_map[key])}")
            else:
                lines.append(f"**{tok}** → {' | '.join(hits)}")
            continue

        # ② 形態素解析（子詞・フォーカス剥離）
        root, meaning = _morph_lookup(key, word_map)
        if root:
            lines.append(f"**{tok}** [→{root}] {meaning}")
            continue

        # ③ 近似一致（編集距離）
        matches = get_close_matches(key, word_map.keys(), n=2, cutoff=0.88)
        if matches:
            hit_strs = [f"{m}（{' / '.join(word_map[m])}）" for m in matches if word_map[m]]
            if hit_strs:
                lines.append(f"**{tok}** ≈ {' | '.join(hit_strs)}")

    return "\n".join(lines) if lines else "（辞書に一致する語が見つかりませんでした）"


# ---------------------------------------------------------------------------
# 既知誤認修正辞書（ms モードの固有名詞バイアス対策）
# key: Whisper が出す誤認形（小文字）→ value: 正しい Basay 語形
# 実運用で誤認が増えたらここに追記する
# ---------------------------------------------------------------------------

# ms モードで頻出するハルシネーション（Whisper が低確信度時に生成するフィラー）
HALLUCINATIONS: set[str] = {
    "dan seterusnya",
    "terima kasih",
    "saya tidak tahu",
    "dan sebagainya",
    "dan lain-lain",
    "sekian terima kasih",
    "assalamualaikum",
    "dengan hormat",
    "untuk maklumat lanjut",
}

CORRECTIONS: dict[str, str] = {
    # yaku（我・主格）への誤認
    "yaakub":   "yaku",
    "yaqub":    "yaku",
    "yacub":    "yaku",
    "yakub":    "yaku",
    "jacob":    "yaku",
    # fine-tuned v1 固有: j→y 語頭誤認
    "jaku":     "yaku",
    # basay への誤認
    "pasai":    "basay",
    "baksaik":  "basay",
    "baksaq":   "basay",
    "masai":    "basay",
    "asai":     "basay",
    # vutsutsa（漢人）への誤認 — スペースなし版のみ
    "butuqsa":  "vutsutsa",
}

# フレーズ単位の誤認修正（トークン置換より先に適用）
PHRASE_CORRECTIONS: dict[str, str] = {
    "butuq sa":  "vutsutsa",
    "butuq sa?": "vutsutsa",
    # fine-tuned v1 固有: auina の分割誤認
    "awin na":   "auina",
    "awin na,":  "auina",
}

# ---------------------------------------------------------------------------
# mi（マオリ語）音韻バイアス → Basay 近似への逆変換ルール
# UI テーブルで編集可能。順序重要（長いパターン・語頭パターンを先に）。
# ---------------------------------------------------------------------------
PHONOLOGICAL_RULES_MI: list[tuple[str, str]] = [
    # ^ = 語頭（トークン単位処理なので ^ が \b と等価）
    (r"tuq",           "tsu"),  # butuq → butsu
    (r"tu(?=[aeiou])", "tsu"),  # tutsa → tsutsa
    (r"tu",            "tsu"),  # putusa → putsusa
    (r"^j(?=[aeiou])", "t"),    # jina → tina（語頭 j のみ）
    (r"^u(?=j)",       "vu"),   # ujusa → vujusa
    (r"j",             "ts"),   # vujusa → vutsusa（語中 j）
    (r"^wh",           "v"),    # whariki → variki
    (r"^f(?=[uioa])",  "v"),    # futusa → vutusa
    (r"^p(?=[uio])",   "v"),    # putusa → vutusa
    (r"wa(?!i)",       "ma"),   # tawa → tama（wai は除外）
]

# UI テキストボックス表示用デフォルト値
# 形式: パターン → 置換  （# 以降はコメント）
# ^ = 語頭、(?=X) = 直後がX、(?!X) = 直後がXでない
DEFAULT_RULES_TEXT = """\
tuq → tsu
tu(?=[aeiou]) → tsu
tu → tsu
^j(?=[aeiou]) → t
^u(?=j) → vu
j → ts
^wh → v
^f(?=[uioa]) → v
^p(?=[uio]) → v
wa(?!i) → ma\
"""


def _rules_from_text(text: str) -> list[tuple[str, str]]:
    """
    テキストボックスの内容からルールリストを生成する。
    形式: パターン → 置換  （# 以降はコメント、空行は無視）
    """
    result: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].strip()  # コメント除去
        if not line or "→" not in line:
            continue
        parts = line.split("→", 1)
        pat, rep = parts[0].strip(), parts[1].strip()
        if not pat:
            continue
        try:
            re.compile(pat)
            result.append((pat, rep))
        except re.error:
            pass
    return result or PHONOLOGICAL_RULES_MI


def _phonological_translate(
    text: str,
    word_map: dict[str, list[str]],
    syllables: set[str],
    rules: list[tuple[str, str]] | None = None,
) -> str:
    """
    mi モード専用：音韻バイアスを Basay 近似に逆変換する。
    rules が指定されない場合は PHONOLOGICAL_RULES_MI を使用。
    """
    active_rules = rules if rules is not None else PHONOLOGICAL_RULES_MI
    tokens = text.split()
    result: list[str] = []

    for tok in tokens:
        clean = re.sub(r"[^a-zA-Z']", "", tok).lower()
        if not clean:
            result.append(tok)
            continue

        translated = clean
        for pattern, repl in active_rules:
            translated = re.sub(pattern, repl, translated)

        if translated == clean:
            result.append(tok)
            continue

        orig_in_dict  = clean in word_map
        trans_in_dict = translated in word_map

        if trans_in_dict and not orig_in_dict:
            result.append(translated)
        elif orig_in_dict:
            result.append(tok)
        elif _segment(translated, syllables) is not None:
            result.append(translated)
        else:
            result.append(tok)

    return " ".join(result)


def _ft_phoneme_fix(text: str, word_map: dict[str, list[str]],
                    morph_set: set[str] | None = None) -> str:
    """
    Fine-tuned Whisper 固有の系統誤認を辞書照合で補正する。
    - b → v（Basay の有声唇歯摩擦音を Whisper が両唇音と混同）
    - k → q / q → k（軟口蓋音・口蓋垂音の混同）
    - j → y（語頭 j を y に: jaku→yaku など）
    - 格標識 u の付着を分離（mal'au → mal'a u、kumokon'u → kumokon' u）

    処理順序:
    1. word_map に直接ヒット → そのまま
    2. 音素変換候補（v/q/k/y 変換）+ u付着分離 を統合チェック
       → 変換後が word_map または morph_set（-um- 形）にヒット → 置換
       → 変換後 + u付着 の場合は stem を抽出してさらにチェック
    3. どれもヒットしない → そのまま
    """
    ms = morph_set or set()

    def _resolve(w: str) -> str | None:
        """w を解決して出力文字列を返す。解決不能なら None。"""
        # word_map 直接ヒット
        if w in word_map:
            return w
        # morph_set ヒット かつ u付着・グロッタル付着でない → そのまま採用
        if w in ms and not w.endswith("u") and not w.endswith("'"):
            return w
        # 格標識 u の付着分離: stem が word_map または morph_set にある
        if w.endswith("u") and len(w) > 2:
            stem = w[:-1]
            if stem in word_map or stem in ms:
                return stem + " u"
            # 末尾グロッタル付きステム（kumokon'u → stem="kumokon'"）→ ' を除いた形も試みる
            if stem.endswith("'"):
                stem_clean = stem[:-1]
                if stem_clean in word_map or stem_clean in ms:
                    return stem_clean + " u"
                # 辞書にない場合も: 'u 末尾は Basay 1sg エンクリティックとして分離
                # 例: kumokon'u → kumokon' u（n' = ŋ なので ' は保持、4文字以上のステムのみ）
                if len(stem) >= 4:
                    return stem + " u"
        # 末尾 ' の除去（kokon'an' → kokon'an など）
        # ただし n' = ŋ（軟口蓋鼻音）の場合は除去しない
        if w.endswith("'") and not w.endswith("n'") and len(w) > 2:
            trimmed = w[:-1]
            if trimmed in word_map or trimmed in ms:
                return trimmed
        return None

    # 音素変換候補リストを生成（元のまま先頭に）
    def _candidates(w: str) -> list[str]:
        cands: list[str] = [w]
        v  = w.replace("b", "v")
        k  = w.replace("q", "k")
        q  = w.replace("k", "q")
        vq = v.replace("k", "q")
        pk = w.replace("p", "k")   # p→k（Whisper が velar k を両唇音 p と混同）
        if v  != w: cands.append(v)
        if k  != w: cands.append(k)
        if q  != w: cands.append(q)
        if vq != w: cands.append(vq)
        if pk != w: cands.append(pk)
        # 語頭 j→y（Basay では語頭半母音は y: jaku→yaku）先頭に挿入して優先
        if w.startswith("j"):
            cands.insert(0, "y" + w[1:])
        # 各候補に対して語中 y→j も適用（複合変換: p→k + y→j など）
        extra: list[str] = []
        for c in list(cands):
            if "y" in c[1:]:
                mid_yj = c[0] + c[1:].replace("y", "j")
                if mid_yj != c and mid_yj not in cands:
                    extra.append(mid_yj)
        cands.extend(extra)
        return cands

    tokens = text.split()
    result: list[str] = []
    for tok in tokens:
        # 末尾句読点（.,!?）を除去してから処理（Basay の ' は保持）
        w = tok.lower().rstrip(".,!?")
        resolved = None
        for cand in _candidates(w):
            resolved = _resolve(cand)
            if resolved is not None:
                break
        # 解決できた場合は句読点なしで出力、できなかった場合も句読点は除去して返す
        result.append(resolved if resolved is not None else w)
    return " ".join(result)


def _rejoin_split_morphemes(text: str, word_map: dict, morph_set: set) -> str:
    """
    隣接トークンを結合して有効な語形になる場合に再結合する。
    例: kokonanijan + a → kokonanijana（-na の a が分離された場合）
    例: kokon'an + ija → kokon'anija（人称エンクリティックが分離された場合）
    最大2トークン先まで貪欲に結合を試みる。
    """
    tokens = text.split()
    result: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        # 結合を試みるのは最初のトークンが単独の有効語でない場合のみ
        # （na + u → nau のような誤結合を防ぐ）
        if i + 1 < len(tokens) and t not in word_map:
            joined2 = t + tokens[i + 1]
            if joined2 in word_map or joined2 in morph_set:
                # さらに3トークン結合も試みる（joined2 も単独有効語でない場合）
                if i + 2 < len(tokens) and joined2 not in word_map:
                    joined3 = joined2 + tokens[i + 2]
                    if joined3 in word_map or joined3 in morph_set:
                        result.append(joined3)
                        i += 3
                        continue
                result.append(joined2)
                i += 2
                continue
        result.append(t)
        i += 1
    return " ".join(result)


def _detect_hallucination(text: str, word_map: dict | None = None,
                          morph_set: set[str] | None = None) -> str | None:
    """
    ハルシネーションを検出して警告メッセージを返す。問題なければ None。
    - 非ラテン文字が全体の20%超 → 言語ドリフト（アラビア語・中国語など）
    - Basay外発音区別符号（ā ē ī ū š ž č 等）が3文字以上 → 欧州語ハルシネーション
    - 同一パターンの繰り返しが10回超 → ループハルシネーション
    - 辞書ヒット率が極端に低い（word_map 指定時）
    """
    if not text:
        return None

    # ① 非ラテン文字比率チェック（アラビア語・CJK・キリルなど）
    non_latin = sum(1 for c in text if ord(c) > 0x024F and c not in " \n\t.,!?'-")
    ratio = non_latin / max(len(text), 1)
    if ratio > 0.20:
        return (
            "⚠️ ハルシネーション検出（非ラテン文字が多すぎます）。\n"
            "この音源は雑音が多く、モデルが認識できなかった可能性があります。\n"
            "音声の品質向上（ノイズ除去）を試みてください。"
        )

    # ② Basay 外発音区別符号チェック（ラトビア語・チェコ語・ポーランド語などを検出）
    # Basay で使用しない発音区別符号: ā ē ī ū ō š ž č ñ ç ß ő ű ä ö ü ł ń
    _NON_BASAY_DIACRITICS = set("āēīūōšžčñçßőűäöüłńģķļņŗ")
    diacritic_count = sum(1 for c in text.lower() if c in _NON_BASAY_DIACRITICS)
    if diacritic_count >= 3:
        return (
            "⚠️ ハルシネーション検出（欧州語ドリフト）。\n"
            "モデルが音源をヨーロッパ言語と誤認しました（検出文字: "
            + ", ".join(sorted({c for c in text.lower() if c in _NON_BASAY_DIACRITICS}))
            + "）。\n音声の品質向上（ノイズ除去）を試みてください。"
        )

    # ③ ループ検出: 同じ単語が10回以上連続
    tokens = text.split()
    if len(tokens) >= 10:
        for i in range(len(tokens) - 9):
            window = tokens[i:i+10]
            if len(set(window)) <= 2:
                return (
                    "⚠️ ハルシネーション検出（繰り返しパターン）。\n"
                    "無音・雑音区間でモデルがループしています。"
                )

    # ④ 辞書ヒット率チェック（Basay モード時のみ）
    if word_map and len(tokens) >= 5:
        def _in_vocab(t: str) -> bool:
            w = t.lower().strip(".,!?'")
            return w in word_map or (morph_set is not None and w in morph_set)
        hits = sum(1 for t in tokens if _in_vocab(t))
        hit_rate = hits / len(tokens)
        if hit_rate < 0.04:  # 4% 未満 = ほぼ辞書ミス
            return (
                f"⚠️ ハルシネーション検出（辞書ヒット率 {hit_rate:.0%}）。\n"
                "転写結果に巴賽語語彙がほとんど含まれていません。\n"
                "音声の品質向上（ノイズ除去）を試みてください。"
            )

    return None


def _apply_corrections(text: str) -> str:
    """既知誤認を確定的に置換する（snap より先に実行）。"""
    # ① フレーズ置換（大文字小文字を無視）
    lower = text.lower()
    for phrase, fix in PHRASE_CORRECTIONS.items():
        lower = lower.replace(phrase, fix)
    # ② トークン置換
    tokens = lower.split()
    return " ".join(
        CORRECTIONS.get(tok, tok) for tok in tokens
    )


# ---------------------------------------------------------------------------
# モデル・辞書の初期化
# ---------------------------------------------------------------------------

MODEL_SIZE = "medium"  # 中国語精度向上（HF Spaces では large-v3）
DEVICE     = "cpu"
COMPUTE    = "int8"

SUPPORTED_LANGUAGES = {
    # Basay 専用モード（切り替えて精度比較）
    "Basay [★ v1 / epoch5]":     "basay-ft",    # v1: WER 25.6%
    "Basay [★ v2 / epoch25]":    "basay-ft-v2", # v2: WER 26.6%
    "Basay [ami] アミ族語 MMS":  "ami",
    "Basay [id] インドネシア語": "id",
    "Basay [ms] マレー語":       "ms",
    "Basay [mi] マオリ語":       "mi",
    # 多言語混合モード
    "多言語（巴賽語 + 繁體中文 + English）": "multilingual",
    # その他
    "繁體中文":  "zh",
    "English":   "en",
    "日本語":    "ja",
}

TITLE = "巴賽語 語音轉文字"
TTS_SPACE_URL = "https://inkuei-basaytts.hf.space/"
SETTINGS_PATH = "/thfbklw86dqnbp97xgesxokbn"

# 主要言語（メイン UI）
MAIN_LANGUAGES = {
    "巴賽語 v1":  "Basay [★ v1 / epoch5]",
    "多語言":     "多言語（巴賽語 + 繁體中文 + English）",
}

# ── basay.tw 統一スタイル ──────────────────────────────────────────────────
ASR_CSS = """
:root {
  --color-deep:   #1a3a52;
  --color-sand:   #f0e6d2;
  --color-algae:  #5a7a6b;
  --color-brick:  #c86d4a;
  --color-drift:  #6b5d54;
  --color-ink:    #2c2620;
  --color-mist:   #fbf7ef;
  --color-line:   rgba(44, 38, 32, 0.12);
  --font-serif: "Noto Serif TC", "Source Han Serif TC", "PingFang TC", serif;
  --font-sans:  "Inter", "Noto Sans TC", "PingFang TC", "Helvetica Neue", Arial, sans-serif;
  --font-mono:  "JetBrains Mono", "Fira Code", ui-monospace, monospace;
  --max-w: 1080px;
  --radius: 6px;
  --shadow-sm: 0 1px 2px rgba(26, 58, 82, 0.08);
}
body, .gradio-container {
  background: var(--color-mist) !important;
  color: var(--color-ink) !important;
  font-family: var(--font-serif) !important;
}
.gradio-container { max-width: none !important; padding: 0 !important; }
.gradio-container .main, .gradio-container main.contain { max-width: none !important; margin: 0 !important; padding: 0 !important; }
.gradio-container .block:has(.site-header),
.gradio-container .block:has(.hero),
.gradio-container .block:has(.site-footer),
.gradio-container .html-container:has(.site-header),
.gradio-container .html-container:has(.hero),
.gradio-container .html-container:has(.site-footer) {
  max-width: none !important; margin: 0 !important; padding: 0 !important; border: 0 !important;
}
.site-header { width: 100%; background: var(--color-deep) !important; color: var(--color-mist) !important; border-bottom: 3px solid var(--color-brick) !important; }
.site-header-inner { max-width: var(--max-w); margin: 0 auto; padding: 1.2rem 1.5rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem; }
.brand { display: flex; flex-direction: column; line-height: 1.2; }
.brand a { color: var(--color-mist) !important; text-decoration: none !important; border-bottom: 0 !important; font-weight: 600; }
.brand-main { color: var(--color-mist) !important; font-size: 1.35rem; letter-spacing: .08em; }
.brand-sub { color: var(--color-sand) !important; font-size: .85rem; font-style: italic; opacity: .85; margin-top: .2em; font-family: var(--font-sans); }
.site-nav ul { list-style: none !important; margin: 0 !important; padding: 0 !important; display: flex; gap: .78rem; flex-wrap: wrap; font-family: var(--font-sans); font-size: .98rem; }
.site-nav li { list-style: none !important; margin: 0 !important; padding: 0 !important; }
.site-nav li::marker { content: "" !important; }
.site-nav a { color: var(--color-mist) !important; text-decoration: none !important; padding: 0 0 2px; border-bottom: 2px solid transparent !important; }
.site-nav a.active, .site-nav a:hover { color: var(--color-sand) !important; border-bottom-color: var(--color-brick) !important; }
.hero { width: 100%; background: linear-gradient(135deg, var(--color-sand) 0%, var(--color-mist) 100%); text-align: center; padding: 3rem 1.5rem 2.5rem; border-bottom: 1px solid var(--color-line); }
.hero h1 { margin: 0 0 .5em; font-family: var(--font-serif); color: var(--color-deep) !important; font-size: 2.2rem; }
.hero .sub { color: var(--color-drift) !important; font-size: 1.05rem; font-style: italic; margin: 0; }
.container { max-width: var(--max-w); margin: 0 auto; padding: 2rem 1.5rem 4rem; }
.asr-card { background: #fff; border: 1px solid var(--color-line); border-top: 4px solid var(--color-brick); border-radius: var(--radius); padding: 1.4rem 1.6rem; margin: 1.2rem 0; box-shadow: var(--shadow-sm); }
.asr-card label, .asr-card .label-wrap span { font-family: var(--font-sans) !important; font-size: .9rem !important; color: var(--color-deep) !important; font-weight: 600 !important; }
.asr-card [role="radiogroup"], .asr-card fieldset .wrap { display: flex !important; gap: .5rem !important; flex-wrap: wrap !important; }
.asr-card label[data-testid$="radio-label"] { border: 1px solid var(--color-line) !important; background: var(--color-mist) !important; color: var(--color-ink) !important; min-width: 5.4rem !important; height: 2.65rem !important; padding: .45em .9em !important; border-radius: var(--radius) !important; cursor: pointer !important; transition: all .15s ease !important; justify-content: center !important; }
.asr-card label[data-testid$="radio-label"].selected { background: var(--color-algae) !important; color: var(--color-mist) !important; border-color: var(--color-algae) !important; box-shadow: 0 0 0 2px rgba(90,122,107,.18) !important; }
.asr-card textarea, .asr-card input { font-family: var(--font-mono) !important; background: var(--color-mist) !important; color: var(--color-ink) !important; border-color: var(--color-line) !important; border-radius: var(--radius) !important; }
.asr-card button.primary { background: var(--color-deep) !important; border-color: var(--color-deep) !important; color: var(--color-mist) !important; font-family: var(--font-sans) !important; font-weight: 600 !important; border-radius: var(--radius) !important; }
.asr-card button.primary:hover { background: var(--color-brick) !important; border-color: var(--color-brick) !important; }
.site-footer { width: 100%; background: var(--color-deep); color: var(--color-sand); text-align: center; padding: 2.5rem 1.5rem 2rem; margin-top: 4rem; font-family: var(--font-sans); font-size: .9rem; border-top: 3px solid var(--color-brick); }
.site-footer a { color: var(--color-sand); border-bottom: 1px dotted rgba(240,230,210,.4); }
.site-footer .tagline { font-family: var(--font-serif); font-style: italic; margin-bottom: .8em; color: var(--color-mist); }
footer:not(.site-footer) { display: none !important; }
/* 進階設定トグルボタン */
.adv-toggle-btn { margin-top: 2rem !important; opacity: 0.45 !important; font-size: 0.8rem !important; background: transparent !important; border: 1px solid var(--color-line) !important; color: var(--color-drift) !important; }
.adv-toggle-btn:hover { opacity: 0.8 !important; }
/* タブ */
.gr-tab-nav { border-bottom: 2px solid var(--color-line) !important; }
.gr-tab-nav button { font-family: var(--font-sans) !important; font-size: 1.15rem !important; font-weight: 700 !important; color: var(--color-drift) !important; border-radius: 0 !important; border: none !important; border-bottom: 3px solid transparent !important; padding: .8rem 1.8rem !important; background: transparent !important; }
.gr-tab-nav button.selected { color: var(--color-deep) !important; border-bottom-color: var(--color-brick) !important; }
@media (max-width: 640px) {
  .site-header-inner { flex-direction: column; align-items: flex-start; }
  .site-nav ul { gap: .75rem; }
  .hero h1 { font-size: 1.8rem; }
}
/* iframe 埋め込み時: ヘッダー・ヒーロー・フッターを非表示 */
html.basay-embedded .site-header,
html.basay-embedded .hero,
html.basay-embedded .site-footer,
html.basay-embedded footer:not(.site-footer) { display: none !important; }
html.basay-embedded .container { padding-top: 0.5rem !important; }
"""

ASR_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono:wght@400;500&family=Noto+Serif+TC:wght@400;500;700&display=swap" rel="stylesheet">
<script>
(() => {
  // iframe 埋め込み検出: ヘッダー・ヒーロー・フッターを非表示
  if (window.self !== window.top) {
    document.documentElement.classList.add('basay-embedded');
  }
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
  const __obs = new MutationObserver(forceLight);
  const __start = () => {
    if (!document.body) { setTimeout(__start, 30); return; }
    __obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    __obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  };
  __start();
  [100, 500, 1500].forEach(t => setTimeout(forceLight, t));
  const hideBadge = () => {
    const nodes = document.querySelectorAll('a, div, header, section, button');
    for (const node of nodes) {
      const text = (node.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const rect = node.getBoundingClientRect?.();
      if (text.includes('inkuei') && text.includes('basayasr') && rect &&
          rect.top < 120 && rect.right > window.innerWidth * 0.55 &&
          rect.width < 520 && rect.height < 140 &&
          ['fixed','absolute','sticky'].includes(getComputedStyle(node).position)) {
        node.style.display = 'none';
      }
    }
  };
  window.addEventListener('load', hideBadge);
  [500, 1500, 3000].forEach(t => setTimeout(hideBadge, t));
})();
</script>
"""

ASR_HEADER_HTML = """
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
  <h1>巴賽語語音轉文字</h1>
  <p class="sub">Basay ASR ⸺ Whisper fine-tuned + 3,000 詞辭典</p>
</section>
"""

ASR_FOOTER_HTML = """
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

print(f"[ASR] Loading whisper-{MODEL_SIZE} ({DEVICE}/{COMPUTE}) ...")
_model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE)
print("[ASR] Model ready.")

# ---------------------------------------------------------------------------
# Fine-tuned Whisper（Basay TTS データで学習した専用モデル）
# ---------------------------------------------------------------------------
_FT_MODEL_DIR    = BASE_DIR / "whisper-basay-finetuned"     # v1: epoch5
_FT_MODEL_DIR_V2 = BASE_DIR / "whisper-basay-finetuned-v2"  # v2: epoch25
_ft_pipelines: dict[str, object] = {}

def _get_ft_pipeline(model_dir):
    """Fine-tuned モデルを遅延ロードする（モデルごとにキャッシュ）。"""
    key = str(model_dir)
    if key in _ft_pipelines:
        return _ft_pipelines[key]
    if not model_dir.exists():
        raise FileNotFoundError(f"Fine-tuned モデルが見つかりません: {model_dir}")
    from transformers import pipeline
    import torch
    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"[FT] Loading {model_dir.name} on {device} ...")
    pipe = pipeline(
        "automatic-speech-recognition",
        model=str(model_dir),
        device=device,
    )
    _ft_pipelines[key] = pipe
    print(f"[FT] {model_dir.name} ready.")
    return pipe

def _transcribe_ft(audio_path: str, version: str = "v1") -> str:
    """Fine-tuned Whisper で音声を転写する。version='v1' or 'v2'"""
    model_dir = _FT_MODEL_DIR_V2 if version == "v2" else _FT_MODEL_DIR
    pipe = _get_ft_pipeline(model_dir)
    result = pipe(audio_path, return_timestamps=True)
    # チャンク結果をテキストに結合
    if isinstance(result.get("chunks"), list):
        return " ".join(c["text"].strip() for c in result["chunks"]).strip()
    return result["text"].strip()


# ---------------------------------------------------------------------------
# MMS (facebook/mms-1b-all) — アミ族語プロキシモード
# ---------------------------------------------------------------------------
_MMS_MODEL_ID  = "facebook/mms-1b-all"
_mms_processor = None
_mms_model     = None

def _ensure_mms() -> None:
    """MMS モデルを遅延ロードする（初回呼び出し時のみ）。"""
    global _mms_processor, _mms_model
    if _mms_model is not None:
        return
    from transformers import Wav2Vec2ForCTC, AutoProcessor
    print(f"[MMS] Loading {_MMS_MODEL_ID} ...")
    _mms_processor = AutoProcessor.from_pretrained(_MMS_MODEL_ID)
    _mms_model     = Wav2Vec2ForCTC.from_pretrained(_MMS_MODEL_ID)
    _mms_model.eval()
    print("[MMS] ロード完了")

def _load_audio_16k(path: str):
    """音声ファイルを 16kHz モノラル numpy 配列として返す。"""
    import soundfile as sf
    import numpy as np
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        from scipy.signal import resample
        audio = resample(audio, int(len(audio) * 16000 / sr)).astype(np.float32)
    return audio

def _transcribe_mms(audio_path: str, lang: str = "ami") -> str:
    """MMS モデルで音声を転写する。"""
    import torch
    _ensure_mms()
    _mms_processor.tokenizer.set_target_lang(lang)
    _mms_model.load_adapter(lang)
    audio  = _load_audio_16k(audio_path)
    inputs = _mms_processor(audio, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        logits = _mms_model(**inputs).logits
    ids = torch.argmax(logits, dim=-1)[0]
    return _mms_processor.decode(ids)

_word_map, _basay_prompt = _load_dictionary()
_syllables = _load_syllables(SYLLABLE_MD)

# 表記揺れエイリアス（ASR出力 → 辞書正規形）
# 辞書に存在する語の別表記を word_map に追加することで、
# セグメンタ・ルックアップ両方で認識できるようにする
_SPELLING_ALIASES: dict[str, str] = {
    "tsuai":  "tsuay",   # tsuwai の ASR 出力形
    "tsuwai": "tsuay",   # 正書法との揺れ
}
for _alias, _canon in _SPELLING_ALIASES.items():
    if _canon in _word_map and _alias not in _word_map:
        _word_map[_alias] = _word_map[_canon]


def _build_morph_set(word_map: dict[str, list[str]]) -> set[str]:
    """
    word_map の全エントリから形態論的変形を生成して set で返す。
    word_map 自体は変更しない（スナップ・分割への副作用を避けるため）。

    Basay の動詞形態論パラダイム（後置辞連鎖）:
      A: -i, -a
      B: -an  (焦点標識)
      C: 人称・数エンクリティック
         短形: -ku -ik -su -is -ta -it -mi -am -mu -im -ia -ja
         長形: -aku -isu -ita -ami -imu -ija -eja
      D: -na  (アスペクト)

    生成パターン: stem × { ∅, B } × { ∅, C } × { ∅, D } × { ∅, -um- }
    + グロッタル停止符落とし形 + 格標識 u 付着形
    """
    _VOWELS = set("aeiouAEIOU")
    _C_SFXS = [
        # 短形
        "ku", "ik", "su", "is", "ta", "it", "mi", "am", "mu", "im", "ia", "ja",
        # 長形
        "aku", "isu", "ita", "ami", "imu", "ija", "eja",
    ]
    _B_SFX = "an"
    _D_SFX = "na"

    def _um(s: str) -> str:
        """-um- 挿中辞を挿入する。"""
        if s and s[0] not in _VOWELS:
            return s[0] + "um" + s[1:]
        return "um" + s

    result: set[str] = set()

    for word in word_map:
        w = word.lower()
        # ASR がグロッタル停止符 ' を落とす場合の形も含める
        w_ng = w.replace("'", "")
        bases = [w] if w_ng == w else [w, w_ng]

        for base in bases:
            um = _um(base)
            b_form = base + _B_SFX          # base + -an
            um_b = _um(b_form)              # -um- + base + -an

            # -um- 形・-an 形・-um-an 形を登録
            result.update([um, b_form, um_b])

            # stem ∈ {base, um, b_form, um_b} に対して
            # C エンクリティック × D アスペクト の全組み合わせを展開
            for stem in (base, um, b_form, um_b):
                # stem のみ（C も D もなし）
                result.add(stem)

                for c in _C_SFXS:
                    sc  = stem + c            # stem + C
                    scd = sc + _D_SFX         # stem + C + D
                    scn = sc + _D_SFX[0]      # stem + C + D の n が付着（ASR 分割）
                    result.update([sc, scd, scn])

                # D のみ（C なし）
                result.add(stem + _D_SFX)

            # 格標識 u 付着形（ASR が "X u" を "Xu" と出力する場合）
            result.add(base + "u")
            result.add(um + "u")
        result.add(w + "u")          # 原形への u 付着も追加

    return result


_morph_set: set[str] = _build_morph_set(_word_map)

# ---------------------------------------------------------------------------
# 転写処理
# ---------------------------------------------------------------------------

def transcribe(
    audio_path: str | None,
    language_label: str,
    user_prompt: str,
    rules_table: object = None,
    alts_text: str | None = None,
    basay_corr_text: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Returns: (転写テキスト, タイムスタンプ付きセグメント, 辞書ルックアップ, 音節解析)
    """
    if audio_path is None:
        return "❌ 音声ファイルを入力してください。", "", "", ""

    lang_code = SUPPORTED_LANGUAGES.get(language_label)
    is_basay  = "Basay" in language_label

    # ------------------------------------------------------------------
    # Fine-tuned Whisper モード（basay-ft）
    # ------------------------------------------------------------------
    _ft_used = False
    if lang_code in ("basay-ft", "basay-ft-v2"):
        version = "v2" if lang_code == "basay-ft-v2" else "v1"
        try:
            plain_raw = _transcribe_ft(audio_path, version=version)
            _ft_used = True
        except FileNotFoundError:
            # FT モデル未インストール → 標準 Whisper (id/Basay prompt) にフォールバック
            lang_code = "id"
            is_basay = True
        except Exception as e:
            return f"❌ Fine-tuned モデルエラー: {e}", "", "", ""

    if _ft_used:

        # ハルシネーション検出
        halluc = _detect_hallucination(plain_raw, word_map=_word_map, morph_set=_morph_set)
        if halluc:
            return halluc, f"[Fine-tuned Whisper {version} 生出力]\n{plain_raw[:300]}…", "", ""

        # UI 補正ルールを最初に適用（ハードコード補正より優先）
        _protected: set[str] = set()
        if basay_corr_text and basay_corr_text.strip():
            plain_raw, _protected = _apply_basay_corrections(plain_raw, basay_corr_text)
        corrected  = _apply_corrections(plain_raw)
        # b→v, k→q 辞書照合変換（fine-tuned モード固有の系統誤認補正）
        corrected  = _ft_phoneme_fix(corrected, _word_map, morph_set=_morph_set)
        # 分離された形態素を再結合（例: kokonanijan a → kokonanijana）
        corrected  = _rejoin_split_morphemes(corrected, _word_map, _morph_set)
        # 語境界回復（融合トークンを辞書最大マッチングで分割）
        segmented  = _segment_words(corrected, _word_map, _syllables)
        plain      = _snap_to_dict(segmented, _word_map, cutoff=0.88, protected=_protected)
        lookup     = _lookup(plain, _word_map)
        syllable_analysis = _analyze_syllables(plain, _syllables)
        timed = (
            f"[Fine-tuned Whisper {version} 生出力]\n{plain_raw}\n\n"
            f"[音韻補正・語境界回復後]\n{segmented}"
        )
        return plain, timed, lookup, syllable_analysis

    # ------------------------------------------------------------------
    # MMS モード（ami）: Whisper をバイパスして MMS モデルを使用
    # ------------------------------------------------------------------
    if lang_code == "ami":
        try:
            plain_raw = _transcribe_mms(audio_path, lang="ami")
        except Exception as e:
            return f"❌ MMS 転写エラー: {e}", "", "", ""

        corrected = _apply_corrections(plain_raw)
        # Amis→Basay 音韻逆変換（常に適用、ルールが空なら PHONOLOGICAL_RULES_MI にフォールバック）
        custom_rules = _rules_from_text(rules_table) if rules_table else None
        corrected = _phonological_translate(corrected, _word_map, _syllables, custom_rules)
        plain  = _snap_to_dict(corrected, _word_map, cutoff=0.88)
        custom_alts = _alts_from_text(alts_text) if alts_text else None
        lookup = _lookup(corrected, _word_map, custom_alts)
        syllable_analysis = _analyze_syllables(plain, _syllables)
        # timed欄: MMS生出力 → 音韻変換後 の両方を表示
        timed = f"[MMS 生出力]\n{plain_raw}\n\n[音韻変換後]\n{corrected}"
        return plain, timed, lookup, syllable_analysis

    # ------------------------------------------------------------------
    # 多言語混合モード（2パス方式）
    # パス1: language="zh" → 繁體中文・English を漢字/英字で取得
    # パス2: fine-tuned v1  → Basay 語を取得
    # マージ: トークンが CJK/英字主体 → zh結果、ラテン主体 → Basay結果
    # ------------------------------------------------------------------
    if lang_code == "multilingual":
        # --- パス1: zh モード ---
        try:
            zh_prompt = (user_prompt or "").strip() or "以下是繁體中文與英語的混合語音。"
            segs_zh, _ = _model.transcribe(
                audio_path,
                beam_size=5,
                language="zh",
                task="transcribe",
                vad_filter=True,
                word_timestamps=False,
                temperature=0.0,
                initial_prompt=zh_prompt,
            )
            zh_segments = list(segs_zh)
        except Exception as e:
            return f"❌ 転写エラー（zh パス）: {e}", "", "", ""

        zh_text = " ".join((s.text or "").strip() for s in zh_segments)

        # --- パス2: fine-tuned v1 ---
        try:
            ft_text = _transcribe_ft(audio_path, version="v1")
            ft_halluc = _detect_hallucination(ft_text, word_map=_word_map, morph_set=_morph_set)
            if ft_halluc:
                ft_text = ""  # ハルシネーションは破棄
        except Exception:
            ft_text = ""

        # 両出力を並記（自動マージなし）
        # ft v1 に Basay 補正パイプラインを適用（UI ルール優先）
        if ft_text:
            _ft_work = ft_text
            _ml_protected: set[str] = set()
            if basay_corr_text and basay_corr_text.strip():
                _ft_work, _ml_protected = _apply_basay_corrections(_ft_work, basay_corr_text)
            ft_corrected = _apply_corrections(_ft_work)
            ft_corrected = _ft_phoneme_fix(ft_corrected, _word_map, morph_set=_morph_set)
            ft_corrected = _rejoin_split_morphemes(ft_corrected, _word_map, _morph_set)
            ft_segmented = _segment_words(ft_corrected, _word_map, _syllables)
        else:
            ft_corrected = ""
            ft_segmented = ""

        # 転写テキスト: Basay語は ft v1 補正後、非Basay部分は zh 漢字で置換
        # 非Basay トークンの連続をひとつの「ギャップ」として zh 出力で埋める
        def _merge_basay_zh(ft_tokens: list[str], zh: str, wmap: dict, syls: set) -> str:
            """
            ft v1 補正トークンを走査し:
            - 辞書ヒット or Basay 音節分割可能 → Basay 語として保持
            - それ以外の連続ギャップ → zh パス出力で置換（zh なければ phonetic のまま）
            """
            zh_fill = zh.strip() if zh.strip() else None
            merged: list[str] = []
            gap_buf: list[str] = []   # 非Basay トークンを一時蓄積
            zh_inserted = False

            for tok in ft_tokens:
                w = tok.lower().strip(".,!?'\"")
                is_basay = (
                    (w in wmap) or
                    (w in _morph_set) or
                    (len(w) <= 2 and w.isalpha()) or
                    (_segment(w, syls) is not None)
                )
                if is_basay:
                    if gap_buf:
                        # ギャップを zh で埋める。zh 使用済みなら phonetic のまま
                        if zh_fill and not zh_inserted:
                            merged.append(zh_fill)
                            zh_inserted = True
                        else:
                            merged.extend(gap_buf)
                        gap_buf = []
                    merged.append(tok)
                else:
                    gap_buf.append(tok)

            # 末尾ギャップ
            if gap_buf:
                if zh_fill and not zh_inserted:
                    merged.append(zh_fill)
                else:
                    merged.extend(gap_buf)

            return " ".join(merged)

        ft_tokens_list = ft_corrected.split() if ft_corrected else []
        plain = _merge_basay_zh(ft_tokens_list, zh_text, _word_map, _syllables) or ft_text or "（認識失敗）"
        timed = (
            f"[Basay fine-tuned v1 生出力]\n{ft_text or '（ハルシネーション検出のため破棄）'}\n\n"
            f"[Basay 補正後]\n{ft_corrected or '—'}"
        )
        lookup = _lookup(ft_segmented, _word_map) if ft_segmented else ""
        syllable_analysis = _analyze_syllables(ft_segmented, _syllables) if ft_segmented else ""
        return plain, timed, lookup, syllable_analysis

    # ------------------------------------------------------------------
    # Whisper モード（既存処理）
    # ------------------------------------------------------------------
    # initial_prompt: ユーザー入力 > 辞書自動生成 > なし
    prompt = (user_prompt or "").strip() or (_basay_prompt if is_basay else "")

    try:
        kwargs: dict = dict(
            beam_size=5,
            language=lang_code,
            task="transcribe",
            vad_filter=True,
            word_timestamps=False,
            temperature=0.0,
        )
        if prompt:
            kwargs["initial_prompt"] = prompt
        segs, _ = _model.transcribe(audio_path, **kwargs)
        segments = list(segs)
    except Exception as e:
        return f"❌ 転写エラー: {e}", "", "", ""

    plain_raw = " ".join((s.text or "").strip() for s in segments)

    if is_basay:
        # ① ハルシネーション検出
        if plain_raw.strip().lower() in HALLUCINATIONS:
            return "⚠️ 音声が短すぎるか不明瞭です。もう少し長く・はっきり話してください。", "", "", ""
        # ② 既知誤認を確定修正
        corrected = _apply_corrections(plain_raw)
        # ③ 音韻逆変換（mi/ms/id モード：言語バイアス → Basay 近似）
        if lang_code in ("mi", "ms", "id"):
            custom_rules = _rules_from_text(rules_table) if rules_table else None
            corrected = _phonological_translate(corrected, _word_map, _syllables, custom_rules)
        # ④ 辞書スナップ（近似語）
        plain = _snap_to_dict(corrected, _word_map, cutoff=0.88)
    else:
        plain = plain_raw

    timed = "\n".join(
        f"[{_fmt(s.start)} → {_fmt(s.end)}]  {s.text.strip()}"
        for s in segments
    ) or plain

    # 辞書ルックアップ：音韻変換後・スナップ前テキストで実施（候補展開含む）
    lookup_text = corrected if is_basay else plain_raw
    custom_alts = _alts_from_text(alts_text) if alts_text else None
    lookup = _lookup(lookup_text, _word_map, custom_alts) if is_basay else ""

    # 音節境界解析（Basay モード：修正後テキストで実施）
    syllable_analysis = _analyze_syllables(plain, _syllables) if is_basay else ""

    return plain, timed, lookup, syllable_analysis


def _snap_to_dict(text: str, word_map: dict[str, list[str]], cutoff: float = 0.88,
                  protected: set[str] | None = None) -> str:
    """
    Basay モード専用の後処理。
    転写された各単語を辞書の最近傍にスナップする。
    短い語ほど高い cutoff を要求（4文字以下 → 0.94、5文字 → 0.92、6文字以上 → cutoff）。
    protected に含まれる単語はスナップしない（UI補正の変換先を保護）。
    """
    if not word_map:
        return text

    _protected = protected or set()
    tokens = text.split()
    corrected = []
    for tok in tokens:
        clean = re.sub(r"[^a-zA-Z']", "", tok).lower()
        if not clean:
            corrected.append(tok)
            continue
        # UI補正の変換先はスナップしない
        if clean in _protected:
            corrected.append(tok)
            continue
        if clean in word_map:
            corrected.append(tok)
            continue
        # 語長に応じた cutoff（短語の誤スナップを防ぐ）
        n = len(clean)
        effective = 0.94 if n <= 4 else (0.92 if n == 5 else cutoff)
        matches = get_close_matches(clean, word_map.keys(), n=1, cutoff=effective)
        if matches:
            snap = matches[0]
            corrected.append(snap if tok.islower() else snap.capitalize())
        else:
            corrected.append(tok)

    return " ".join(corrected)


def _fmt(sec: float) -> str:
    m = int(sec // 60)
    return f"{m:02d}:{sec % 60:05.2f}"


def _denoise_audio(audio_path: str, strength: float = 0.75) -> str:
    """
    scipy の STFT を使ったスペクトル減算ノイズ除去（noisereduce 不要）。
    冒頭 0.5 秒をノイズプロファイルとして使用。
    strength: 0.0（除去なし）〜 1.0（強除去）
    """
    import soundfile as sf
    import numpy as np
    import tempfile
    from scipy.signal import stft, istft

    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # STFT パラメータ
    nperseg = 512
    noverlap = nperseg // 2

    # ノイズプロファイル（冒頭 0.5 秒）
    noise_len = int(sr * 0.5)
    noise_sample = audio[:noise_len] if len(audio) > noise_len else audio

    _, _, noise_stft = stft(noise_sample, fs=sr, nperseg=nperseg, noverlap=noverlap)
    noise_power = np.mean(np.abs(noise_stft) ** 2, axis=1, keepdims=True)

    # 信号全体の STFT
    freqs, times, sig_stft = stft(audio, fs=sr, nperseg=nperseg, noverlap=noverlap)

    # スペクトル減算
    sig_mag   = np.abs(sig_stft)
    sig_phase = np.angle(sig_stft)
    noise_mag = np.sqrt(noise_power)

    # strength に応じて減算量を調整
    reduced_mag = np.maximum(sig_mag - strength * noise_mag, 0.0)
    reduced_stft = reduced_mag * np.exp(1j * sig_phase)

    # 逆 STFT
    _, denoised = istft(reduced_stft, fs=sr, nperseg=nperseg, noverlap=noverlap)
    denoised = denoised.astype(np.float32)

    # クリップ
    peak = np.max(np.abs(denoised))
    if peak > 0:
        denoised = denoised / peak * 0.95

    out = tempfile.NamedTemporaryFile(suffix="_denoised.wav", delete=False)
    out.close()
    sf.write(out.name, denoised, sr)
    return out.name


def _extract_audio_from_video(video_path: str) -> str:
    """MP4 などの動画ファイルから音声を抽出して WAV パスを返す。ffmpeg を使用。"""
    import subprocess, tempfile
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    out.close()
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",                  # 映像なし
        "-ac", "1",             # モノラル
        "-ar", "16000",         # 16kHz
        "-f", "wav", out.name,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg エラー: {result.stderr.decode()[:200]}")
    return out.name


# ---------------------------------------------------------------------------
# 設定ファイル 読込 / 保存
# ---------------------------------------------------------------------------

import tempfile as _tempfile

# HF Spaces では /tmp/ への書き込みは常に可能
_TMP_DIR   = Path(_tempfile.gettempdir()) / "basay_config"
_TMP_RULES = _TMP_DIR / "rules.txt"
_TMP_ALTS  = _TMP_DIR / "alts.txt"


def _load_config() -> tuple[str, str]:
    """config/ → /tmp/ → デフォルト の順で設定を読込む。"""
    if RULES_CFG.exists():
        rules = RULES_CFG.read_text(encoding="utf-8")
    elif _TMP_RULES.exists():
        rules = _TMP_RULES.read_text(encoding="utf-8")
    else:
        rules = DEFAULT_RULES_TEXT

    if ALTS_CFG.exists():
        alts = ALTS_CFG.read_text(encoding="utf-8")
    elif _TMP_ALTS.exists():
        alts = _TMP_ALTS.read_text(encoding="utf-8")
    else:
        alts = DEFAULT_ALTS_TEXT

    return rules, alts


_BASAY_CORR_CFG  = CONFIG_DIR / "basay_corrections.txt"
_TMP_BASAY_CORR  = _TMP_DIR / "basay_corrections.txt"

DEFAULT_BASAY_CORR_TEXT = """\
# Basay fine-tuned 補正ルール（1行1ルール、→ または -> どちらも可）
#
# ルール種別:
#   トークン（完全一致）:     jaku → yaku
#   フレーズ（空白含む）:     awin na → auina
#   プレフィックス（右端-）:  Unaba- → bumba-    ※語頭を置換
#   サフィックス（左端-）:    -iau → -ijau       ※語末を置換
#   インフィックス（両端-）:  -ja- → -ia-        ※語中のみ（語頭は除外）
#
jaku → yaku
awin na → auina
"""


def _load_basay_corrections() -> str:
    if _BASAY_CORR_CFG.exists():
        return _BASAY_CORR_CFG.read_text(encoding="utf-8")
    if _TMP_BASAY_CORR.exists():
        return _TMP_BASAY_CORR.read_text(encoding="utf-8")
    return DEFAULT_BASAY_CORR_TEXT


def save_basay_corrections(text: str) -> str:
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        _BASAY_CORR_CFG.write_text(text, encoding="utf-8")
        return "✅ 保存しました（config/basay_corrections.txt）"
    except Exception:
        pass
    try:
        _TMP_DIR.mkdir(exist_ok=True)
        _TMP_BASAY_CORR.write_text(text, encoding="utf-8")
        return "⚠️ /tmp/ に保存（再起動でリセット）"
    except Exception as e:
        return f"❌ 保存失敗: {e}"


def _apply_basay_corrections(text: str, rules_text: str) -> tuple[str, set[str]]:
    """UI 入力のルールテキストを解析して補正を適用する。
    形式: 誤認形 → 正規形  （→ または -> どちらも可）

    ルール種別:
    - スペースを含む左辺       → フレーズルール（文字列置換）
    - 両端が - で囲まれた左辺   → インフィックスルール（語中のみ、語頭は対象外）
                               例: -ja- → -ia-
    - 右端のみ -               → プレフィックスルール（語頭一致 → 語頭置換）
                               例: Unaba- → bumba-
    - 左端のみ -               → サフィックスルール（語末一致 → 語末置換）
                               例: -iau → -ijau
    - それ以外                → トークンルール（完全一致）

    戻り値: (補正後テキスト, 変換先ワードのセット)
    変換先ワードセットは _snap_to_dict の protected に渡してスナップを防ぐ。
    """
    phrase_rules:  list[tuple[str, str]] = []
    prefix_rules:  list[tuple[str, str]] = []   # (core_src, core_dst) 語頭一致
    suffix_rules:  list[tuple[str, str]] = []   # (core_src, core_dst) 語末一致
    infix_rules:   list[tuple[str, str]] = []   # (core_src, core_dst) 語中のみ
    token_rules:   dict[str, str] = {}
    protected:     set[str] = set()

    for line in rules_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sep = "→" if "→" in line else ("->" if "->" in line else None)
        if sep is None:
            continue
        left, _, right = line.partition(sep)
        src = left.strip().strip('"').strip("'")
        dst = right.strip().strip('"').strip("'")
        if not src or not dst:
            continue

        src_l = src.startswith("-")
        src_r = src.endswith("-")

        if " " in src:
            phrase_rules.append((src.lower(), dst))
            for w in dst.lower().split(): protected.add(w)
        elif src_l and src_r and len(src) > 2:
            # インフィックスルール: -ja- → -ia-
            infix_rules.append((src[1:-1].lower(), dst.strip("-").lower()))
            protected.add(dst.strip("-").lower())
        elif src_r and not src_l:
            # プレフィックスルール: Unaba- → bumba-
            prefix_rules.append((src[:-1].lower(), dst.rstrip("-").lower()))
            protected.add(dst.rstrip("-").lower())
        elif src_l and not src_r:
            # サフィックスルール: -iau → -ijau
            suffix_rules.append((src[1:].lower(), dst.lstrip("-").lower()))
            protected.add(dst.lstrip("-").lower())
        else:
            token_rules[src.lower()] = dst
            for w in dst.lower().split(): protected.add(w)

    result = text.lower()
    for src, dst in phrase_rules:
        result = result.replace(src, dst)
    tokens = result.split()

    def _apply_token(t: str) -> str:
        # 完全一致
        if t in token_rules:
            return token_rules[t]
        stripped = t.rstrip(".,!?")
        if stripped != t and stripped in token_rules:
            return token_rules[stripped]
        out = t
        modified = False
        # プレフィックスルール（語頭一致）
        for ps, pd in prefix_rules:
            if out.startswith(ps):
                out = pd + out[len(ps):]
                modified = True
                break
        # サフィックスルール（語末一致）
        if not modified:
            for ss, sd in suffix_rules:
                if out.endswith(ss):
                    out = out[:-len(ss)] + sd
                    modified = True
                    break
        # インフィックスルール（語頭・語末以外に適用）
        # プレフィックス/サフィックスが適用済みの場合は適用しない
        if not modified:
            _VOWELS_SET = set("aeiou")
            for cs, cd in infix_rules:
                if cs in out[1:]:
                    pos = out.index(cs, 1)
                    # 語末一致は除外（語末サフィックスを壊さない）
                    if pos + len(cs) >= len(out):
                        continue
                    # j が直前の母音に続く場合は除外（-ija- 等のC-suffix を保護）
                    if cs and cs[0] == "j" and pos > 0 and out[pos - 1] in _VOWELS_SET:
                        continue
                    out = out[:pos] + cd + out[pos + len(cs):]
        return out

    return " ".join(_apply_token(t) for t in tokens), protected


def save_config(rules_text: str, alts_text: str) -> str:
    """UI の編集内容を保存する。config/ に書けなければ /tmp/ に保存（セッション中のみ有効）。"""
    # まず config/ ディレクトリに試みる
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        RULES_CFG.write_text(rules_text, encoding="utf-8")
        ALTS_CFG.write_text(alts_text,  encoding="utf-8")
        return "✅ 保存しました（config/）。ローカルで git push すれば永続化できます。"
    except Exception:
        pass

    # 失敗した場合は /tmp/ に保存（Space 再起動でリセット）
    try:
        _TMP_DIR.mkdir(exist_ok=True)
        _TMP_RULES.write_text(rules_text, encoding="utf-8")
        _TMP_ALTS.write_text(alts_text,  encoding="utf-8")
        return "⚠️ /tmp/ に保存しました（再起動でリセット）。永続化はローカルで git push してください。"
    except Exception as e:
        return f"❌ 保存失敗: {e}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

def transcribe_either(
    upload_file: str | None,
    mic_audio: str | None,
    language_label: str,
    denoise: bool,
    denoise_strength: float,
    user_prompt: str,
    rules_table: object = None,
    alts_text: str | None = None,
    basay_corr_text: str | None = None,
) -> tuple[str, str, str, str]:
    """アップロード・マイク録音を統合して転写する。動画ファイルは音声を自動抽出。"""
    path = upload_file or mic_audio
    if path and Path(path).suffix.lower() in _VIDEO_EXTS:
        try:
            path = _extract_audio_from_video(path)
        except Exception as e:
            return f"❌ 動画音声抽出エラー: {e}", "", "", ""
    if path and denoise:
        try:
            path = _denoise_audio(path, strength=denoise_strength)
        except Exception as e:
            return f"❌ ノイズ除去エラー: {e}", "", "", ""
    return transcribe(path, language_label, user_prompt, rules_table, alts_text, basay_corr_text)


def build_ui() -> gr.Blocks:
    _init_rules, _init_alts = _load_config()
    _init_basay_corr = _load_basay_corrections()

    with gr.Blocks(title=TITLE, css=ASR_CSS, head=ASR_HEAD_HTML) as demo:

        # ── ヘッダー（basay.tw 統一デザイン）──
        gr.HTML(ASR_HEADER_HTML)

        # ════════════════════════════════════════
        # メインページ
        # ════════════════════════════════════════
        with gr.Column(elem_id="basay-main-page", elem_classes=["container"]) as main_col:

            with gr.Row():
                # ── 左：入力 ──
                with gr.Column(scale=1, elem_classes=["asr-card"]):
                    with gr.Tabs():
                        with gr.Tab("📂 上傳檔案"):
                            upload_input = gr.File(
                                label="上傳音訊／影片（wav / mp3 / m4a / mp4 / mov 等）",
                                file_types=[
                                    ".wav", ".mp3", ".m4a", ".ogg", ".flac",
                                    ".opus", ".webm", ".mp4", ".mov", ".avi", ".mkv",
                                ],
                                type="filepath",
                            )
                        with gr.Tab("🎤 錄音"):
                            mic_input = gr.Audio(
                                label="麥克風錄音",
                                sources=["microphone"],
                                type="filepath",
                            )

                    lang_radio = gr.Radio(
                        label="語言",
                        choices=list(MAIN_LANGUAGES.keys()),
                        value="巴賽語 v1",
                    )
                    submit_btn = gr.Button("🎙️ 開始辨識", variant="primary", size="lg")

                # ── 右：結果 ──
                with gr.Column(scale=1, elem_classes=["asr-card"]):
                    plain_out = gr.Textbox(label="辨識結果", lines=6)
                    lookup_out = gr.Textbox(label="辭典查詢", lines=4, interactive=False)

            # サンプル音声
            sample_dir = BASE_DIR / "samples"
            if sample_dir.exists():
                samples = sorted(sample_dir.glob("*.wav")) + sorted(sample_dir.glob("*.mp3"))
                if samples:
                    gr.Examples(
                        examples=[[str(f)] for f in samples],
                        inputs=[upload_input],
                        label="範例音訊",
                    )

            # 進階設定トグル（目立たないボタン）
            adv_btn = gr.Button("⚙ 進階設定", elem_classes=["adv-toggle-btn"], size="sm")

        # ════════════════════════════════════════
        # 進階設定（デフォルト非表示）
        # ════════════════════════════════════════
        with gr.Column(elem_id="basay-settings-page", elem_classes=["container"], visible=False) as settings_col:
            back_btn = gr.Button("← 返回辨識頁面", size="sm", variant="secondary")
            gr.HTML("<h2 style='color:var(--color-deep);border-bottom:1px solid var(--color-line);padding-bottom:.3em;margin-top:1rem;'>⚙️ 進階設定</h2>")

            with gr.Tabs():

                with gr.Tab("輸出詳情"):
                    timed_out = gr.Textbox(label="時間戳記分段", lines=6, interactive=False)
                    syllable_out = gr.Textbox(label="音節邊界解析  ✅完整  ❓部分／不明", lines=5, interactive=False)

                with gr.Tab("語言 / 降噪 / 提示詞"):
                    language_dd = gr.Dropdown(
                        label="語言（完整列表）",
                        choices=list(SUPPORTED_LANGUAGES.keys()),
                        value="Basay [★ v1 / epoch5]",
                    )
                    gr.Markdown("*選擇此處後，主頁面「語言」Radio 的設定將被覆蓋。*")
                    prompt_box = gr.Textbox(
                        label="提示詞（選填）— 留空則自動從辭典生成",
                        placeholder="例：Basay, Ketagalan, Kivahiv, 淡水 …",
                        lines=2,
                    )
                    if _basay_prompt:
                        gr.Markdown(f"**辭典提示詞（自動）：** `{_basay_prompt[:120]}…`")
                    denoise_cb = gr.Checkbox(label="🔇 降噪（適用於歷史音源等雜訊較多的情況）", value=False)
                    denoise_strength = gr.Slider(
                        minimum=0.1, maximum=1.0, value=0.75, step=0.05,
                        label="降噪強度（0.1=弱 / 1.0=強）", visible=False,
                    )
                    denoise_cb.change(fn=lambda x: gr.update(visible=x), inputs=[denoise_cb], outputs=[denoise_strength])

                with gr.Tab("音韻補正規則"):
                    with gr.Tabs():
                        with gr.Tab("巴賽語 fine-tuned 補正"):
                            gr.Markdown(
                                "格式（每行一條）：`誤辨形 → 正規形` / `Prefix- → Replacement-` / "
                                "`-Suffix → -Replacement` / `-infix- → -replacement-` / `phrase → result`"
                            )
                            basay_corr_box = gr.Textbox(
                                value=_init_basay_corr, label="巴賽語補正規則",
                                lines=15, max_lines=30,
                                placeholder="例：\njaku → yaku\nawin na → auina\nUnaba- → bumaba-",
                            )
                            with gr.Row():
                                save_basay_btn = gr.Button("💾 儲存補正規則", variant="secondary")
                                save_basay_status = gr.Textbox(label="", lines=1, interactive=False)
                            save_basay_btn.click(fn=save_basay_corrections, inputs=[basay_corr_box], outputs=[save_basay_status])

                        with gr.Tab("mi / ami 音韻轉換"):
                            with gr.Row():
                                with gr.Column():
                                    rules_df = gr.Textbox(value=_init_rules, label="音韻轉換規則", lines=12, max_lines=20)
                                with gr.Column():
                                    alts_df = gr.Textbox(value=_init_alts, label="音素候補表", lines=15, max_lines=25)
                            with gr.Row():
                                save_btn = gr.Button("💾 儲存 mi/ami 設定", variant="secondary")
                                save_status = gr.Textbox(label="", lines=1, interactive=False)
                            save_btn.click(fn=save_config, inputs=[rules_df, alts_df], outputs=[save_status])

        # ── フッター ──
        gr.HTML(ASR_FOOTER_HTML)

        # ── 送出ロジック ──
        def _resolve_language(radio_val: str, dd_val: str) -> str:
            default_dd = "Basay [★ v1 / epoch5]"
            if dd_val != default_dd:
                return dd_val
            return MAIN_LANGUAGES.get(radio_val, default_dd)

        def transcribe_ui(upload, mic, radio_val, dd_val, denoise, strength, prompt, rules, alts, basay_corr):
            lang_label = _resolve_language(radio_val, dd_val)
            path = upload or mic
            if path and Path(path).suffix.lower() in _VIDEO_EXTS:
                try:
                    path = _extract_audio_from_video(path)
                except Exception as e:
                    return f"❌ 影片音訊擷取錯誤：{e}", "", "", ""
            if path and denoise:
                try:
                    path = _denoise_audio(path, strength=strength)
                except Exception as e:
                    return f"❌ 降噪錯誤：{e}", "", "", ""
            return transcribe(path, lang_label, prompt, rules, alts, basay_corr)

        submit_btn.click(
            fn=transcribe_ui,
            inputs=[upload_input, mic_input, lang_radio, language_dd, denoise_cb, denoise_strength, prompt_box, rules_df, alts_df, basay_corr_box],
            outputs=[plain_out, timed_out, lookup_out, syllable_out],
        )

        # 進階設定 ↔ メインページ 切り替え
        adv_btn.click(
            fn=lambda: (gr.update(visible=False), gr.update(visible=True)),
            outputs=[main_col, settings_col],
        )
        back_btn.click(
            fn=lambda: (gr.update(visible=True), gr.update(visible=False)),
            outputs=[main_col, settings_col],
        )

    return demo


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
