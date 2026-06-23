"""
generate_pdfs.py
巴賽語論文 HTML → PDF 変換スクリプト
Chrome headless モードを使用
"""

import subprocess
import os
import sys
import time

# Chrome のパスを探す
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

chrome_path = None
for p in CHROME_CANDIDATES:
    if os.path.exists(p):
        chrome_path = p
        break

if not chrome_path:
    print("ERROR: Chrome / Edge が見つかりません。")
    sys.exit(1)

print(f"ブラウザ: {chrome_path}")

# パスの設定
BASE = r"C:\Users\user\Downloads\basay-grammar\webpage\basaytw\basay-tw"
PAPERS = os.path.join(BASE, "research", "papers")
os.makedirs(PAPERS, exist_ok=True)

# 変換リスト: (HTMLの相対パス, 出力PDFファイル名)
PAGES = [
    ("research/2026-06-basay-syllable-B/index.html",           "basay_syllable_B_zh260623.pdf"),
    ("research/2026-06-basay-syllable-B/ja/index.html",        "basay_syllable_B_ja260623.pdf"),
    ("research/2026-06-basay-syllable-B/en/index.html",        "basay_syllable_B_en260623.pdf"),
    ("research/2026-06-basay-syllable-TM/index.html",          "basay_syllable_TM_zh260623.pdf"),
    ("research/2026-06-basay-syllable-TM/ja/index.html",       "basay_syllable_TM_ja260623.pdf"),
    ("research/2026-06-basay-syllable-TM/en/index.html",       "basay_syllable_TM_en260623.pdf"),
    ("research/2026-06-basay-syllable-revised/index.html",     "basay_syllable_revised_zh260623.pdf"),
    ("research/2026-06-basay-syllable-revised/ja/index.html",  "basay_syllable_revised_ja260623.pdf"),
    ("research/2026-06-basay-syllable-revised/en/index.html",  "basay_syllable_revised_en260623.pdf"),
]

success = 0
fail = 0

for html_rel, pdf_name in PAGES:
    html_abs = os.path.join(BASE, html_rel.replace("/", os.sep))
    html_url  = "file:///" + html_abs.replace("\\", "/")
    pdf_path  = os.path.join(PAPERS, pdf_name)

    print(f"\n変換中: {html_rel}")
    print(f"  → {pdf_name}")

    cmd = [
        chrome_path,
        "--headless=new",
        "--disable-gpu",
        "--run-all-compositor-stages-before-draw",
        "--disable-extensions",
        f"--print-to-pdf={pdf_path}",
        "--print-to-pdf-no-header",
        "--no-sandbox",
        html_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        time.sleep(2)  # Chrome が書き込むまで少し待つ
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
            print(f"  ✓ 成功 ({os.path.getsize(pdf_path):,} bytes)")
            success += 1
        else:
            print(f"  ✗ 失敗（ファイルが空か未生成）")
            if result.stderr:
                print(f"     stderr: {result.stderr[:200]}")
            fail += 1
    except subprocess.TimeoutExpired:
        print("  ✗ タイムアウト（60秒超過）")
        fail += 1
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        fail += 1

print(f"\n{'='*40}")
print(f"完了: 成功 {success} 本 / 失敗 {fail} 本")
print(f"PDFの保存先: {PAPERS}")
