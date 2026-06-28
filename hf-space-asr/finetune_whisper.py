"""
Basay ASR — Whisper fine-tuning スクリプト
==========================================
Google Colab (GPU) または Mac (MPS/CPU) で動作します。

## Colab での使い方
1. basay-tw フォルダを Google Drive にアップロード
2. BasayASR フォルダも Google Drive にアップロード
3. 以下のセルを Colab で実行:

    from google.colab import drive
    drive.mount('/content/drive')
    %cd /content/drive/MyDrive/BasayASR
    !pip install -q transformers datasets accelerate evaluate jiwer soundfile librosa
    !python finetune_whisper.py --audio-base /content/drive/MyDrive/basay-tw

## ローカル (Mac) での使い方
    pip install transformers datasets accelerate evaluate jiwer soundfile librosa
    python finetune_whisper.py

## HF Hub へのプッシュ
    python finetune_whisper.py --push-to-hub inkuei/whisper-small-basay

## 完了後の確認
    python finetune_whisper.py --eval-only --model-dir ./whisper-basay-finetuned
"""

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

# ---------------------------------------------------------------------------
# 引数パーサー
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model",       default="openai/whisper-small",
                   help="ベースモデル（openai/whisper-small / medium）")
    p.add_argument("--dataset-dir", default="dataset",
                   help="prepare_dataset.py が出力した JSONL フォルダ")
    p.add_argument("--audio-base",  default=None,
                   help="音声ファイルのベースパス（JSONL のパスを上書き）")
    p.add_argument("--output-dir",  default="whisper-basay-finetuned",
                   help="モデル保存先")
    p.add_argument("--push-to-hub", metavar="REPO_ID", default=None,
                   help="HF Hub リポジトリ ID（例: inkuei/whisper-small-basay）")
    p.add_argument("--epochs",      type=int, default=30)
    p.add_argument("--batch-size",  type=int, default=None,
                   help="デフォルト: GPU=16, MPS=8, CPU=4")
    p.add_argument("--lr",          type=float, default=1e-5)
    p.add_argument("--warmup-steps",type=int, default=200)
    p.add_argument("--eval-only",   action="store_true",
                   help="学習せず評価のみ実行")
    return p.parse_args()


# ---------------------------------------------------------------------------
# デバイス検出
# ---------------------------------------------------------------------------

def detect_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# データセットロード
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def resolve_audio_path(record: dict, audio_base: Path | None) -> str:
    """JSONL の相対パス（例: a/abalx.mp3）を絶対パスに変換する。
    audio_base が None の場合はそのまま返す（絶対パスとして扱う）。
    """
    rel = record["audio"]  # 例: "a/abalx.mp3"
    if audio_base is not None:
        return str(audio_base / rel)
    # フォールバック: カレントディレクトリ基点
    return str(Path(rel).resolve())


def make_hf_dataset(records: list[dict], audio_base: Path | None):
    """records から HuggingFace Dataset を作成する。"""
    from datasets import Dataset, Audio

    paths = [resolve_audio_path(r, audio_base) for r in records]
    texts = [r["text"] for r in records]

    # 存在確認
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"⚠️  音声ファイルが見つからない: {len(missing)} 件（例: {missing[0]}）")

    ds = Dataset.from_dict({"audio": paths, "text": texts})
    ds = ds.cast_column("audio", Audio(sampling_rate=16000))
    return ds


# ---------------------------------------------------------------------------
# 前処理
# ---------------------------------------------------------------------------

def build_prepare_fn(feature_extractor, tokenizer):
    def prepare(batch):
        # 音声 → log-mel スペクトログラム
        audio = batch["audio"]
        inputs = feature_extractor(
            audio["array"],
            sampling_rate=audio["sampling_rate"],
            return_tensors="np",
        )
        batch["input_features"] = inputs.input_features[0]

        # テキスト → token ID
        batch["labels"] = tokenizer(batch["text"]).input_ids
        return batch
    return prepare


# ---------------------------------------------------------------------------
# DataCollator（Whisper 公式推奨）
# ---------------------------------------------------------------------------

@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:
    processor: Any

    def __call__(self, features: list[dict]) -> dict[str, torch.Tensor]:
        # input_features はすでに固定長（30秒）なのでそのままスタック
        input_features = [{"input_features": f["input_features"]} for f in features]
        batch = self.processor.feature_extractor.pad(
            input_features, return_tensors="pt"
        )

        # labels はパディング
        label_features = [{"input_ids": f["labels"]} for f in features]
        labels_batch   = self.processor.tokenizer.pad(
            label_features, return_tensors="pt"
        )
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch.attention_mask.ne(1), -100
        )
        # BOS トークンが先頭にある場合は除去（Whisper の仕様）
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all():
            labels = labels[:, 1:]

        batch["labels"] = labels
        return batch


# ---------------------------------------------------------------------------
# WER 評価
# ---------------------------------------------------------------------------

def build_compute_metrics(tokenizer):
    import evaluate
    wer_metric = evaluate.load("wer")

    def compute_metrics(pred):
        pred_ids  = pred.predictions
        label_ids = pred.label_ids
        label_ids[label_ids == -100] = tokenizer.pad_token_id

        pred_str  = tokenizer.batch_decode(pred_ids,  skip_special_tokens=True)
        label_str = tokenizer.batch_decode(label_ids, skip_special_tokens=True)

        # 小文字・空白正規化
        pred_str  = [s.lower().strip() for s in pred_str]
        label_str = [s.lower().strip() for s in label_str]

        wer = wer_metric.compute(predictions=pred_str, references=label_str)
        return {"wer": round(wer, 4)}

    return compute_metrics


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    device = detect_device()
    print(f"[Info] デバイス: {device}")
    print(f"[Info] ベースモデル: {args.model}")

    # ライブラリ import
    from transformers import (
        WhisperFeatureExtractor,
        WhisperTokenizer,
        WhisperProcessor,
        WhisperForConditionalGeneration,
        Seq2SeqTrainingArguments,
        Seq2SeqTrainer,
    )

    # ---------------------------------------------------------------------------
    # モデル・プロセッサ初期化
    # ---------------------------------------------------------------------------
    feature_extractor = WhisperFeatureExtractor.from_pretrained(args.model)
    tokenizer = WhisperTokenizer.from_pretrained(
        args.model,
        language=None,   # 言語非固定（Basay は Whisper 未収録）
        task="transcribe",
    )
    processor = WhisperProcessor.from_pretrained(args.model)

    if args.eval_only:
        model = WhisperForConditionalGeneration.from_pretrained(args.output_dir)
    else:
        model = WhisperForConditionalGeneration.from_pretrained(args.model)

    # 言語トークンを強制しない設定
    model.config.forced_decoder_ids = None
    model.config.suppress_tokens    = []

    # ---------------------------------------------------------------------------
    # データセットロード
    # ---------------------------------------------------------------------------
    dataset_dir = Path(args.dataset_dir)
    audio_base  = Path(args.audio_base) if args.audio_base else None

    print("\nデータセットロード中...")
    train_records = load_jsonl(dataset_dir / "train.jsonl")
    val_records   = load_jsonl(dataset_dir / "val.jsonl")
    test_records  = load_jsonl(dataset_dir / "test.jsonl")
    print(f"  train: {len(train_records)}, val: {len(val_records)}, test: {len(test_records)}")

    train_ds = make_hf_dataset(train_records, audio_base)
    val_ds   = make_hf_dataset(val_records,   audio_base)
    test_ds  = make_hf_dataset(test_records,  audio_base)

    # ---------------------------------------------------------------------------
    # 前処理
    # ---------------------------------------------------------------------------
    print("\n前処理中（音声 → log-mel）...")
    prepare_fn = build_prepare_fn(feature_extractor, tokenizer)

    train_ds = train_ds.map(prepare_fn, remove_columns=["audio", "text"],
                            num_proc=1, desc="train")
    val_ds   = val_ds.map(prepare_fn,   remove_columns=["audio", "text"],
                            num_proc=1, desc="val")
    test_ds  = test_ds.map(prepare_fn,  remove_columns=["audio", "text"],
                            num_proc=1, desc="test")

    collator = DataCollatorSpeechSeq2SeqWithPadding(processor=processor)

    # ---------------------------------------------------------------------------
    # 評価のみモード
    # ---------------------------------------------------------------------------
    if args.eval_only:
        print("\n評価実行中...")
        from transformers import Seq2SeqTrainer
        trainer = Seq2SeqTrainer(
            model=model,
            data_collator=collator,
            compute_metrics=build_compute_metrics(tokenizer),
        )
        results = trainer.evaluate(eval_dataset=test_ds,
                                   metric_key_prefix="test",
                                   max_length=128,
                                   num_beams=5)
        print(f"\nテスト WER: {results['test_wer']:.4f}")
        return

    # ---------------------------------------------------------------------------
    # 学習設定
    # ---------------------------------------------------------------------------
    batch_size = args.batch_size or (16 if device == "cuda" else 8 if device == "mps" else 4)
    grad_accum = max(1, 16 // batch_size)  # 実効バッチ = 16

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=args.lr,
        warmup_steps=args.warmup_steps,
        predict_with_generate=True,
        generation_max_length=128,
        generation_num_beams=1,        # 学習中は greedy で高速化
        fp16=(device == "cuda"),
        evaluation_strategy="epoch",
        save_strategy="epoch",
        logging_steps=50,
        load_best_model_at_end=True,
        metric_for_best_model="wer",
        greater_is_better=False,
        push_to_hub=(args.push_to_hub is not None),
        hub_model_id=args.push_to_hub,
        report_to="none",
        # Mac MPS 対応
        use_mps_device=(device == "mps"),
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=collator,
        compute_metrics=build_compute_metrics(tokenizer),
        tokenizer=processor.feature_extractor,
    )

    # ---------------------------------------------------------------------------
    # 学習実行
    # ---------------------------------------------------------------------------
    print(f"\n学習開始（{args.epochs} epochs, batch={batch_size}, lr={args.lr}）...")
    trainer.train()

    # ---------------------------------------------------------------------------
    # 保存・評価・Push
    # ---------------------------------------------------------------------------
    trainer.save_model(args.output_dir)
    processor.save_pretrained(args.output_dir)
    print(f"\n✅ モデル保存: {args.output_dir}")

    print("\nテストセット評価中...")
    results = trainer.evaluate(
        eval_dataset=test_ds,
        metric_key_prefix="test",
        max_length=128,
        num_beams=5,
    )
    print(f"テスト WER: {results.get('test_wer', 'N/A'):.4f}")

    if args.push_to_hub:
        print(f"\nHF Hub にプッシュ中: {args.push_to_hub}")
        trainer.push_to_hub()
        print(f"✅ https://huggingface.co/{args.push_to_hub}")


if __name__ == "__main__":
    main()
