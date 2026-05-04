#!/usr/bin/env python3
"""
gen_audio.py — basay_text.py を使った賢い音声生成ラッパー

============================================================
gen_audio.sh との違い:
  ・表記（display）だけを渡せば、slug と TTS テキストが自動派生される
  ・--slug / --tts で個別に手動上書き可
  ・既存ファイルがあれば --force なしではスキップ

============================================================
使用例:
  # 自動派生（最も普通の使い方）
  python3 gen_audio.py "Makawas ita mau Basay"
      → makawas_ita_mau_basay.wav に "Ma:kawas ita mau Basay" を合成

  # slug を手動上書き
  python3 gen_audio.py "kalili'" --slug kalili

  # TTS テキストを手動上書き（プロソディを完全制御）
  python3 gen_audio.py "Lennaita" --tts "Le:nnaita,"

  # 既存上書き
  python3 gen_audio.py "tsu" --force

  # ドライラン（合成せず派生結果だけ表示）
  python3 gen_audio.py "Pina i tia na zijan kuwarij-an-a ni qupa" --dry-run

============================================================
出力先:
  <SITE_ROOT>/education/phrasebook/audio/ipay/<slug>.wav
  <SITE_ROOT>/education/phrasebook/audio/hokkien/<slug>.wav

  そして audio_manifest.tsv に行を追記（重複は更新）。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# basay_text を同ディレクトリから import
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import basay_text  # noqa: E402

SITE_ROOT = SCRIPT_DIR.parent
AUDIO_ROOT = SITE_ROOT / "education" / "phrasebook" / "audio"
IPAY_DIR = AUDIO_ROOT / "ipay"
HOKKIEN_DIR = AUDIO_ROOT / "hokkien"
MANIFEST = SCRIPT_DIR / "audio_manifest.tsv"

IPAY_VOICE = os.environ.get("IPAY_VOICE", "bsy+f1")
HOKKIEN_VOICE = os.environ.get("HOKKIEN_VOICE", "bsystd")


def check_espeak():
    if shutil.which("espeak-ng") is None:
        print("Error: espeak-ng が見つかりません。", file=sys.stderr)
        print("  sudo apt install espeak-ng   # Debian/Ubuntu", file=sys.stderr)
        sys.exit(3)


# ─── 音量正規化設定 ──────────────────────────────────────────
# ffmpeg loudnorm:
#   I    = -16 LUFS (target integrated loudness; podcast/voice 標準)
#   TP   = -1.5 dBTP (true peak ceiling, クリッピング回避)
#   LRA  = 11 LU (loudness range)
#   linear=true で単発パスでも安定（短いクリップ向け）
# 環境変数 BASAY_NO_NORMALIZE=1 で無効化可
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true"


def normalize_audio(wav: Path):
    """生成直後の wav を ffmpeg loudnorm で音量正規化する。
    bsy voice は phoneme ごとに音圧バランスが揃っていないため、
    辞書/フレーズブック用途では単語間の音量差が気になる。LUFS で
    knock したものに揃えると聞き比べが安定する。"""
    if os.environ.get("BASAY_NO_NORMALIZE") == "1":
        return
    if shutil.which("ffmpeg") is None:
        print("  warn: ffmpeg が無いため正規化スキップ", file=sys.stderr)
        return
    tmp = wav.with_suffix(".norm.wav")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav),
        "-af", LOUDNORM_FILTER,
        str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True)
        tmp.replace(wav)
    except subprocess.CalledProcessError as e:
        print(f"  warn: 正規化失敗 ({wav.name}): {e}", file=sys.stderr)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def synth(text: str, voice: str, out_wav: Path):
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["espeak-ng", "-v", voice, text, "-w", str(out_wav)]
    subprocess.run(cmd, check=True)
    normalize_audio(out_wav)


def update_manifest(display: str, slug: str):
    """audio_manifest.tsv に行を upsert（display をキーに更新）。"""
    rows = []
    header = "# TEXT\tSLUG\n"
    if MANIFEST.exists():
        with MANIFEST.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines and lines[0].startswith("#"):
                header = lines[0]
                lines = lines[1:]
            for ln in lines:
                ln = ln.rstrip("\n")
                if not ln:
                    continue
                parts = ln.split("\t", 1)
                if len(parts) == 2 and parts[0] == display:
                    continue  # 既存行は捨てて新しい行に置換
                rows.append(ln)
    rows.append(f"{display}\t{slug}")
    with MANIFEST.open("w", encoding="utf-8") as f:
        f.write(header)
        for r in rows:
            f.write(r + "\n")


def main():
    ap = argparse.ArgumentParser(
        description="表記から slug と TTS テキストを派生して音声を合成。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("display", nargs="+", help="表記（複数語ならクォート推奨）")
    ap.add_argument("--slug", help="slug を手動上書き")
    ap.add_argument("--tts", help="TTS 入力テキストを手動上書き")
    ap.add_argument("--force", action="store_true",
                    help="既存 wav があっても上書き")
    ap.add_argument("--dry-run", action="store_true",
                    help="派生結果を表示するだけで合成しない")
    ap.add_argument("--no-manifest", action="store_true",
                    help="audio_manifest.tsv を更新しない")
    args = ap.parse_args()

    display = " ".join(args.display)
    d = basay_text.derive(display, args.slug, args.tts)

    print(f"display: {d['display']}")
    print(f"slug:    {d['slug']}")
    print(f"tts:     {d['tts']}")

    if args.dry_run:
        return 0

    if not d["slug"]:
        print("Error: 派生 slug が空です。手動 --slug が必要です。", file=sys.stderr)
        return 2

    check_espeak()

    ipay_wav = IPAY_DIR / f"{d['slug']}.wav"
    hokkien_wav = HOKKIEN_DIR / f"{d['slug']}.wav"

    for wav, voice, label in [
        (ipay_wav, IPAY_VOICE, "IPay"),
        (hokkien_wav, HOKKIEN_VOICE, "台語"),
    ]:
        if wav.exists() and not args.force:
            print(f"  [{label}:{voice}] スキップ（既存）: {wav.relative_to(SITE_ROOT)}")
            continue
        print(f"→ [{label}:{voice}] {d['tts']!r} → {wav.relative_to(SITE_ROOT)}")
        synth(d["tts"], voice, wav)

    if not args.no_manifest:
        update_manifest(d["display"], d["slug"])

    print(f"✓ done: {d['slug']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
