#!/usr/bin/env python3
"""
daily_add.py — 今日の巴賽語エントリを 5 項目入力で追加し、自動 push

============================================================
使い方
============================================================

【対話モード（推奨）】
    python3 daily_add.py
    →  date, word, slug(任意), gloss, usage を順に聞かれる
    →  音声生成 → git add → commit → push まで自動

【ワンライナー】
    python3 daily_add.py --word "belan'" --gloss "count" --usage "計算"

    オプション:
      --date YYYY-MM-DD   既定: 今日
      --word "..."        表記（必須）
      --slug "..."        slug 上書き（任意、空なら自動派生）
      --gloss "..."       グロス
      --usage "..."       用例（中国語）
      --no-audio          音声生成をスキップ
      --no-push           git push をスキップ（commit だけ実行）
      --no-commit         commit と push をスキップ
      -y, --yes           確認なしで実行

【未来日のまとめ追加】
    対話モードで日付を 2026-05-10 のように指定すれば
    その日付エントリが追加されます。push しても、
    fill-forward ロジックでその日まで前のエントリが表示されるので、
    1 週間分まとめて投入しておく運用が可能です。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
DAILY_JSON = SITE_ROOT / "data" / "daily.json"


def prompt(label, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except EOFError:
        return default
    return val if val else default


def confirm(msg):
    try:
        r = input(f"{msg} [Y/n]: ").strip().lower()
    except EOFError:
        return True
    return r in ('', 'y', 'yes')


def derive_slug(word, override=None):
    """basay_text.slug を呼ぶ（同じ規則で派生）。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    import basay_text
    return basay_text.slug(word, override or None)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD（既定: 今日）")
    ap.add_argument("--word", help="表記")
    ap.add_argument("--slug", help="slug 上書き（任意）")
    ap.add_argument("--gloss", help="グロス")
    ap.add_argument("--usage", help="用例")
    ap.add_argument("--no-audio", action="store_true", help="音声生成をスキップ")
    ap.add_argument("--no-commit", action="store_true", help="git commit / push をスキップ")
    ap.add_argument("--no-push", action="store_true", help="commit はするが push しない")
    ap.add_argument("-y", "--yes", action="store_true", help="確認なしで実行")
    args = ap.parse_args()

    today = date.today().isoformat()

    print("─" * 60)
    print("  日々の巴賽語エントリ追加")
    print("─" * 60)

    d = args.date or prompt("1) 日付 (YYYY-MM-DD)", today)
    w = args.word or prompt("2) 表記 (Basay)")
    s = args.slug if args.slug is not None else prompt("3) slug 上書き (空欄で自動)", "")
    g = args.gloss or prompt("4) グロス (linguistic gloss)")
    u = args.usage or prompt("5) 用例 (中国語)")

    if not w:
        print("Error: 表記が空です。中止します。", file=sys.stderr)
        return 1
    if not d:
        d = today

    derived_slug = derive_slug(w, s)
    print()
    print("─" * 60)
    print("  確認")
    print("─" * 60)
    print(f"  date:  {d}")
    print(f"  word:  {w}")
    if s:
        print(f"  slug:  {s}（手動上書き）")
    else:
        print(f"  slug:  {derived_slug}（自動派生）")
    print(f"  gloss: {g}")
    print(f"  usage: {u}")
    print()

    if not args.yes and not confirm("追加して進めますか？"):
        print("中止しました。")
        return 0

    # JSON 読み込み
    if not DAILY_JSON.exists():
        print(f"Error: {DAILY_JSON} がありません。", file=sys.stderr)
        return 1
    try:
        with DAILY_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: daily.json の JSON 解析失敗: {e}", file=sys.stderr)
        return 1

    # エントリ作成（slug は手動指定の時のみ書き出す）
    entry = {"word": w}
    if s:
        entry["slug"] = s
    entry["gloss"] = g
    entry["usage"] = u

    if d in data:
        if not args.yes and not confirm(f"  ※ {d} の既存エントリを上書きします。よいですか？"):
            print("中止しました。")
            return 0

    data[d] = entry

    with DAILY_JSON.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✓ daily.json 更新")

    # 音声生成
    if not args.no_audio:
        print()
        print("─ 音声生成 ─" * 4)
        rc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "build_daily_audio.py")]
        ).returncode
        if rc != 0:
            print("Warning: 音声生成でエラーが発生しました。", file=sys.stderr)
            print("        手動で確認してから再実行してください。", file=sys.stderr)
            return 2

    # git
    if args.no_commit:
        print("\n（git 操作をスキップ）")
        return 0

    print()
    print("─ git add / commit / push ─")
    os.chdir(SITE_ROOT)
    subprocess.run(["git", "add", "-A"], check=True)
    msg = f"Daily {d} {w}"
    cm = subprocess.run(["git", "commit", "-m", msg])
    if cm.returncode != 0:
        print("（コミットするものなし、または失敗）")
        return cm.returncode

    if args.no_push:
        print(f"✓ committed (push スキップ): {msg}")
        return 0

    pr = subprocess.run(["git", "push"])
    if pr.returncode != 0:
        print("Error: push 失敗。手動で確認してください。", file=sys.stderr)
        return pr.returncode

    print(f"✓ pushed: {msg}")
    print()
    print("数十秒〜2 分で https://basay.tw/ に反映されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
