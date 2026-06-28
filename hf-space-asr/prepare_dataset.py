"""
Basay ASR fine-tuning 用データセット準備スクリプト
=================================================
Usage:
    python prepare_dataset.py [--push-to-hub HF_REPO_ID]

例:
    python prepare_dataset.py
    python prepare_dataset.py --push-to-hub inkuei/basay-asr-dataset

出力:
    dataset/train.jsonl  (80%)
    dataset/val.jsonl    (10%)
    dataset/test.jsonl   (10%)

各行の形式:
    {"audio": "/abs/path/to/file.mp3", "text": "abal'", "source": "B"}
"""

import json
import random
import argparse
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# パス設定（このスクリプトから見た相対パス）
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).parent
DICT_JSON    = SCRIPT_DIR / "dictionary" / "dictionary.json"

# basay-tw フォルダ（音声ファイル）は BasayASR の隣にある想定
# 実際のパスに合わせて変更してください
AUDIO_BASE   = SCRIPT_DIR.parent / "basay-tw" / "dictionary" / "audio" / "ipay"
# もし上記が見つからない場合の候補パス
AUDIO_BASES  = [
    SCRIPT_DIR.parent / "basay-tw" / "dictionary" / "audio" / "ipay",
    SCRIPT_DIR.parent / "basay-tw" / "basay-tw" / "dictionary" / "audio" / "ipay",
    Path.home() / "Downloads" / "basay-tw" / "dictionary" / "audio" / "ipay",
    Path.home() / "Downloads" / "basay-tw" / "basay-tw" / "dictionary" / "audio" / "ipay",
    Path.home() / "Documents" / "basay-tw" / "dictionary" / "audio" / "ipay",
    Path.home() / "Documents" / "basay-tw" / "basay-tw" / "dictionary" / "audio" / "ipay",
]

OUT_DIR = SCRIPT_DIR / "dataset"

SEED = 42


def find_audio_base() -> Path | None:
    for p in AUDIO_BASES:
        if p.exists():
            return p
    return None


def normalize_text(text: str) -> str:
    """テキストを正規化する。"""
    # パイプ区切り（複数形）は最初の語を使用
    if "|" in text:
        text = text.split("|")[0]
    text = text.strip()
    # 末尾のピリオドを除去
    text = text.rstrip(".")
    return text.strip()


def build_pairs(dict_path: Path, audio_base: Path) -> list[dict]:
    """dictionary.json から (audio_path, text) ペアを構築する。"""
    d = json.loads(dict_path.read_text(encoding="utf-8"))

    source_prio = {"B": 0, "T": 1, "M": 2}
    slug_map: dict[str, dict] = {}

    for e in d:
        src = e.get("source", "")
        if src not in source_prio:
            continue

        audio = e.get("audio", {})
        slug  = audio.get("slug", "")
        if not slug:
            continue

        # ipay ファイルパスを構築
        # パス例: dictionary/audio/ipay/a/abalx.mp3
        ipay_rel = audio.get("ipay", "")
        if not ipay_rel:
            continue

        # ipay_rel から初期文字ディレクトリとファイル名を取得
        ipay_file = Path(ipay_rel).name   # abalx.mp3
        ipay_dir  = Path(ipay_rel).parent.name  # a
        ipay_path = audio_base / ipay_dir / ipay_file

        if not ipay_path.exists():
            continue

        text = normalize_text(e["basay"])
        if not text:
            continue

        # 相対パス（ipay フォルダ基点）を保存 → Colab でも使える
        audio_rel = f"{ipay_dir}/{ipay_file}"

        prio = source_prio[src]
        if slug not in slug_map or prio < slug_map[slug]["prio"]:
            slug_map[slug] = {
                "audio":  audio_rel,   # 例: "a/abalx.mp3"
                "text":   text,
                "source": src,
                "slug":   slug,
                "prio":   prio,
            }

    pairs = [
        {"audio": v["audio"], "text": v["text"], "source": v["source"]}
        for v in slug_map.values()
    ]
    return pairs


def split_dataset(pairs: list[dict], seed: int = SEED) -> tuple[list, list, list]:
    """80/10/10 でランダム分割する。"""
    random.seed(seed)
    data = pairs[:]
    random.shuffle(data)
    n = len(data)
    n_val  = int(n * 0.10)
    n_test = int(n * 0.10)
    test  = data[:n_test]
    val   = data[n_test:n_test + n_val]
    train = data[n_test + n_val:]
    return train, val, test


def save_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  保存: {path}  ({len(records)} 件)")


def push_to_hub(train, val, test, repo_id: str) -> None:
    """HuggingFace Hub にデータセットをプッシュする。"""
    from datasets import Dataset, DatasetDict, Audio

    def make_hf_dataset(records: list[dict]) -> Dataset:
        return Dataset.from_dict({
            "audio":  [r["audio"]  for r in records],
            "text":   [r["text"]   for r in records],
            "source": [r["source"] for r in records],
        }).cast_column("audio", Audio(sampling_rate=16000))

    ds = DatasetDict({
        "train": make_hf_dataset(train),
        "validation": make_hf_dataset(val),
        "test":  make_hf_dataset(test),
    })
    print(f"\nHuggingFace Hub にプッシュ中: {repo_id}")
    ds.push_to_hub(repo_id, private=True)
    print(f"完了: https://huggingface.co/datasets/{repo_id}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-to-hub", metavar="REPO_ID",
                        help="HF Hub のデータセット ID（例: inkuei/basay-asr-dataset）")
    args = parser.parse_args()

    # 音声ベースパスを探す
    audio_base = find_audio_base()
    if audio_base is None:
        print("❌ ipay 音声フォルダが見つかりません。")
        print("   以下のいずれかに basay-tw フォルダを置いてください:")
        for p in AUDIO_BASES:
            print(f"   {p}")
        return

    print(f"✅ 音声フォルダ: {audio_base}")

    # ペア構築
    print("\n辞書からペアを構築中...")
    pairs = build_pairs(DICT_JSON, audio_base)
    print(f"ユニーク音声ペア数: {len(pairs)}")

    # 統計
    src_dist = Counter(p["source"] for p in pairs)
    wlen_dist = Counter(len(p["text"].split()) for p in pairs)
    print(f"ソース別: {dict(src_dist)}")
    print(f"語数分布: {dict(sorted(wlen_dist.items()))}")

    # 分割
    train, val, test = split_dataset(pairs)
    print(f"\n分割: train={len(train)}, val={len(val)}, test={len(test)}")

    # 保存
    print("\nJSONL 保存中...")
    save_jsonl(OUT_DIR / "train.jsonl", train)
    save_jsonl(OUT_DIR / "val.jsonl",   val)
    save_jsonl(OUT_DIR / "test.jsonl",  test)

    # HF Hub プッシュ（オプション）
    if args.push_to_hub:
        push_to_hub(train, val, test, args.push_to_hub)

    print("\n✅ 完了")
    print(f"   次のステップ: Colab で finetune_whisper.ipynb を実行してください")
    print(f"   または: python finetune_whisper.py --dataset {OUT_DIR}")


if __name__ == "__main__":
    main()
