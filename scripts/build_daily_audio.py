#!/usr/bin/env python3
"""
build_daily_audio.py — data/daily.json から音声を一括生成

============================================================
何をする？
============================================================
data/daily.json を読み、各日付エントリ（"default" を含む）について
  ・entry.word  → 表記
  ・entry.slug  → 任意の手動 slug 上書き（空なら自動派生）
を取り出し、対応する
  education/phrasebook/audio/ipay/<slug>.wav
  education/phrasebook/audio/hokkien/<slug>.wav
が両方揃っていなければ gen_audio.py を呼んで合成する。

明日以降に daily.json へ新しい日付を追加した場合も、
このスクリプトを 1 回叩けば未生成のものだけ生成される。

============================================================
使い方
============================================================
  # 未生成のものだけ生成（普通の使い方）
  python3 build_daily_audio.py

  # 全件強制再生成
  python3 build_daily_audio.py -f

  # 何が生成されるかだけ確認（合成しない）
  python3 build_daily_audio.py --dry-run

  # 別の daily.json を指定
  python3 build_daily_audio.py --json ../data/daily.json

============================================================
出力例
============================================================
  default      Makawas ita mau Basay        → makawas_ita_mau_basay   [skip]
  2026-04-21   lusa                         → lusa                    [make]
  2026-04-25   Luai balmo'n, san'ajau       → luai_balmoxn_sanxajau   [make]
  ─────────────────────────────────────────
  total: 6   made: 2   skipped: 4   failed: 0
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

# basay_text を同ディレクトリから import（slug 派生のため）
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import basay_text  # noqa: E402

SITE_ROOT = SCRIPT_DIR.parent
DEFAULT_JSON = SITE_ROOT / "data" / "daily.json"
AUDIO_ROOT = SITE_ROOT / "education" / "phrasebook" / "audio"
IPAY_DIR = AUDIO_ROOT / "ipay"
HOKKIEN_DIR = AUDIO_ROOT / "hokkien"
GEN_AUDIO = SCRIPT_DIR / "gen_audio.py"


def both_wavs_exist(slug: str) -> bool:
    return (IPAY_DIR / f"{slug}.wav").exists() and (HOKKIEN_DIR / f"{slug}.wav").exists()


def call_gen_audio(display: str, slug_override: str | None, force: bool) -> int:
    cmd = [sys.executable, str(GEN_AUDIO), display]
    if slug_override:
        cmd += ["--slug", slug_override]
    if force:
        cmd += ["--force"]
    return subprocess.run(cmd).returncode


def main():
    ap = argparse.ArgumentParser(
        description="data/daily.json の全エントリの音声を一括生成。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--json", default=str(DEFAULT_JSON),
                    help=f"対象 JSON（既定: {DEFAULT_JSON}）")
    ap.add_argument("-f", "--force", action="store_true",
                    help="既存 wav も上書き再生成")
    ap.add_argument("--dry-run", action="store_true",
                    help="派生結果と判定だけ表示し合成しない")
    args = ap.parse_args()

    json_path = Path(args.json)
    if not json_path.is_file():
        print(f"Error: {json_path} が見つかりません。", file=sys.stderr)
        return 1

    with json_path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: {json_path} の JSON 解析に失敗: {e}", file=sys.stderr)
            return 1

    if not isinstance(data, dict):
        print(f"Error: {json_path} のトップレベルがオブジェクトではありません。", file=sys.stderr)
        return 1

    # default を先頭、その他は日付昇順
    keys = []
    if "default" in data:
        keys.append("default")
    keys += sorted(k for k in data.keys() if k != "default")

    total = made = skipped = failed = 0
    print(f"source: {json_path}")
    print("─" * 64)

    for key in keys:
        entry = data.get(key)
        if not isinstance(entry, dict):
            continue
        word = (entry.get("word") or "").strip()
        slug_override = (entry.get("slug") or "").strip() or None
        if not word:
            print(f"  [{key}] (空エントリ — skip)")
            continue

        derived = basay_text.derive(word, slug_override, None)
        slug = derived["slug"]
        total += 1

        if not slug:
            print(f"  [{key}] {word!r} — slug が空（手動 slug 必須） ✗")
            failed += 1
            continue

        exists = both_wavs_exist(slug)
        action = "skip" if (exists and not args.force) else "make"
        prefix = "DRY " if args.dry_run else ""
        print(f"  [{key:<10}] {word:<32} → {slug:<28} [{prefix}{action}]")

        if action == "skip":
            skipped += 1
            continue

        if args.dry_run:
            made += 1  # ドライランでは「生成予定」として計上
            continue

        rc = call_gen_audio(word, slug_override, args.force)
        if rc == 0:
            made += 1
        else:
            failed += 1
            print(f"    ✗ gen_audio.py rc={rc}")

    print("─" * 64)
    label_made = "would-make" if args.dry_run else "made"
    print(f"total: {total}   {label_made}: {made}   skipped: {skipped}   failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
