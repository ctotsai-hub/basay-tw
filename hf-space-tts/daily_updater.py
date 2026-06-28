"""daily_updater.py — basay.tw 「今日の巴賽語」投稿セクション.

inkuei-basaytts Space に統合される追加 UI セクション。
URL `/daily-update` で表示が切り替わる（既存 main / analysis ページは温存）。

依存：
  - basay_text (既存 v3): derive() / slug() / tts_text()
  - app.py が提供する synth_to_wav(text, voice_short, tts_override=None) -> bytes

環境変数（HF Space Secrets / Variables に登録）:
  GITHUB_TOKEN     contents:write 権限の Fine-grained PAT（basay-tw 専用）
  SUBMIT_TOKEN     フォーム認証用の合言葉
  BASAY_GH_OWNER   default: ctotsai-hub
  BASAY_GH_REPO    default: basay-tw
  BASAY_GH_BRANCH  default: main
  BASAY_DAILY_JSON default: data/daily.json
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
import tempfile
import traceback
from typing import Any, Callable

import gradio as gr

import basay_text  # existing v3 in this Space
from github_client import GitHubClient, GitHubError, build_audio_repo_path

log = logging.getLogger("basay.daily_updater")

# --- environment ----------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
SUBMIT_TOKEN = os.environ.get("SUBMIT_TOKEN", "")
GH_OWNER = os.environ.get("BASAY_GH_OWNER", "ctotsai-hub")
GH_REPO = os.environ.get("BASAY_GH_REPO", "basay-tw")
GH_BRANCH = os.environ.get("BASAY_GH_BRANCH", "main")
DAILY_JSON_PATH = os.environ.get("BASAY_DAILY_JSON", "data/daily.json")


# --- CSS / JS (appended to the existing Blocks) ---------------------------

DAILY_PAGE_CSS = """
.daily-updater-page { display: none !important; }
html.basay-daily .main-page { display: none !important; }
html.basay-daily .analysis-page { display: none !important; }
html.basay-daily .daily-updater-page { display: block !important; }
.daily-updater-page .status-box { font-family: var(--font-sans); }
.daily-updater-page .status-box code { font-family: var(--font-mono); }
.daily-updater-page .hint {
  color: var(--color-drift);
  font-family: var(--font-sans);
  font-size: .85rem;
  margin-top: 1rem;
}
"""

# 既存 HEAD_HTML 内の path detection に追加するスニペット.
# app.py 側で HEAD_HTML を組み立てる際に取り込む.
DAILY_PAGE_JS_SNIPPET = (
    "  const __dpath = window.location.pathname.replace(/\\/+$/, '');\n"
    "  if (__dpath === '/daily-update' || __dpath === '/d') {\n"
    "    document.documentElement.classList.add('basay-daily');\n"
    "  }\n"
)


# --- helpers --------------------------------------------------------------

def _today_iso_tw() -> str:
    """台北時間（UTC+8）の今日."""
    tz = dt.timezone(dt.timedelta(hours=8))
    return dt.datetime.now(tz).date().isoformat()


def _validate_date(s: str) -> str:
    return dt.date.fromisoformat((s or "").strip()).isoformat()


def _auth(token: str) -> None:
    if not SUBMIT_TOKEN:
        raise RuntimeError(
            "サーバ側に SUBMIT_TOKEN が設定されていません。"
            " Space Settings → Variables and secrets で登録してください。"
        )
    if not hmac.compare_digest((token or "").strip(), SUBMIT_TOKEN.strip()):
        raise PermissionError("認証トークンが一致しません。")


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


def _preview_fn(word: str, slug_in: str, tts_in: str) -> tuple[str, str, str]:
    word = (word or "").strip()
    if not word:
        return "", "", ""
    d = basay_text.derive(
        word,
        slug_override=_normalize_optional(slug_in),
        tts_override=_normalize_optional(tts_in),
    )
    return d["display"], d["slug"], d["tts"]


def _dry_run_status(date_key: str, d: dict[str, Any],
                    ipay_size: int, hok_size: int) -> str:
    return (
        f"### ✅ Dry run 成功（コミットなし）\n\n"
        f"- **date**: `{date_key}`\n"
        f"- **slug**: `{d['slug']}`\n"
        f"- **tts**: `{d['tts']}`\n"
        f"- ipay.wav: {ipay_size:,} bytes\n"
        f"- hokkien.wav: {hok_size:,} bytes\n\n"
        f"Dry run を外して再送信すると GitHub に commit します。"
    )


def _success_status(date_key: str, d: dict[str, Any],
                    r_json: dict, r_ipay: dict, r_hok: dict,
                    ipay_path: str, hok_path: str) -> str:
    def short(r: dict) -> str:
        s = ((r or {}).get("commit") or {}).get("sha", "")
        if s:
            return s[:7]
        return "(skipped)" if (r or {}).get("skipped") else "?"
    return (
        f"### ✅ コミット成功\n\n"
        f"- **date**: `{date_key}` ｜ **slug**: `{d['slug']}`\n"
        f"- **tts**: `{d['tts']}`\n\n"
        f"| ファイル | SHA |\n|---|---|\n"
        f"| `{DAILY_JSON_PATH}` | `{short(r_json)}` |\n"
        f"| `{ipay_path}` | `{short(r_ipay)}` |\n"
        f"| `{hok_path}` | `{short(r_hok)}` |\n\n"
        f"GitHub Pages の自動デプロイは 1〜2 分で反映されます。"
    )


def _make_submit_fn(synth_to_wav: Callable[..., bytes]):

    def submit(token: str, date_str: str, word: str, gloss: str, usage: str,
               slug_in: str, tts_in: str, dry_run: bool):
        try:
            _auth(token)
            date_key = _validate_date(date_str)
            word = (word or "").strip()
            if not word:
                raise ValueError("Basay 表記（word）を入力してください。")
            gloss = (gloss or "").strip()
            usage = (usage or "").strip()
            if not gloss:
                raise ValueError("gloss を入力してください。")

            slug_override = _normalize_optional(slug_in)
            tts_override = _normalize_optional(tts_in)
            d = basay_text.derive(word, slug_override=slug_override,
                                  tts_override=tts_override)
            slug = d["slug"]

            log.info("submit: date=%s slug=%s tts=%s", date_key, slug, d["tts"])

            ipay_wav = synth_to_wav(word, "bsy", tts_override=tts_override)
            hok_wav = synth_to_wav(word, "bsystd", tts_override=tts_override)

            ipay_tmp = tempfile.NamedTemporaryFile(
                prefix="ipay_daily_", suffix=".wav", delete=False)
            ipay_tmp.write(ipay_wav)
            ipay_tmp.close()
            hok_tmp = tempfile.NamedTemporaryFile(
                prefix="hok_daily_", suffix=".wav", delete=False)
            hok_tmp.write(hok_wav)
            hok_tmp.close()

            if dry_run:
                status = _dry_run_status(date_key, d, len(ipay_wav), len(hok_wav))
                return status, ipay_tmp.name, hok_tmp.name

            if not GITHUB_TOKEN:
                raise RuntimeError(
                    "サーバ側に GITHUB_TOKEN が設定されていません。"
                    " contents:write 権限付き PAT を Space Secrets に登録してください。"
                )

            gh = GitHubClient(
                token=GITHUB_TOKEN,
                owner=GH_OWNER, repo=GH_REPO, branch=GH_BRANCH,
            )

            entry: dict[str, Any] = {
                "word": d["display"],
                "gloss": gloss,
                "usage": usage,
            }
            if slug_override is not None:
                entry["slug"] = slug_override
            if tts_override is not None:
                entry["tts"] = tts_override

            r_json = gh.update_daily_entry(
                date_key, entry, path=DAILY_JSON_PATH,
                commit_message=f"Daily: {date_key} {d['display']}")
            ipay_path = build_audio_repo_path(slug, "ipay")
            hok_path = build_audio_repo_path(slug, "hokkien")
            r_ipay = gh.put_audio(
                ipay_path, ipay_wav,
                f"audio: ipay/{slug}.wav ({date_key})")
            r_hok = gh.put_audio(
                hok_path, hok_wav,
                f"audio: hokkien/{slug}.wav ({date_key})")

            status = _success_status(date_key, d, r_json, r_ipay, r_hok,
                                     ipay_path, hok_path)
            return status, ipay_tmp.name, hok_tmp.name

        except (PermissionError, ValueError, RuntimeError, GitHubError) as e:
            return (f"### ❌ {type(e).__name__}\n\n```\n{e}\n```", None, None)
        except Exception:  # noqa: BLE001
            log.exception("daily_updater submit unexpected")
            return (
                f"### ❌ 予期せぬエラー\n\n```\n{traceback.format_exc()}\n```",
                None,
                None,
            )

    return submit


# --- UI section -----------------------------------------------------------

def build_daily_section(synth_to_wav: Callable[..., bytes]) -> None:
    """既存 Blocks の中で呼ぶ。Column を追加して click handler を結線する."""

    submit_fn = _make_submit_fn(synth_to_wav)

    with gr.Column(elem_classes=["container", "daily-updater-page"]):
        gr.Markdown(
            "## 今日の巴賽語 ⸺ Daily Updater",
            elem_classes=["section-title"],
        )
        gr.HTML(
            "<p class='hint'>"
            "iPhone でも投稿可能。"
            "<strong>Dry run</strong> で音声・派生を確認 → "
            "外して送信すると <code>ctotsai-hub/basay-tw</code> に "
            "<code>data/daily.json</code> と "
            "<code>audio/{ipay,hokkien}/&lt;slug&gt;.wav</code> が "
            "直接 commit されます。GitHub Pages が 1〜2 分で反映。"
            "</p>"
        )
        with gr.Group(elem_classes=["tts-card"]):
            token_in = gr.Textbox(
                label="認証トークン",
                placeholder="Space Secrets の SUBMIT_TOKEN と同じ文字列",
                type="password",
            )
            with gr.Row():
                date_in = gr.Textbox(
                    label="日付 (YYYY-MM-DD)",
                    value=_today_iso_tw(),
                    scale=1,
                )
                word_in = gr.Textbox(
                    label="Basay 表記（word）",
                    placeholder="例: zanum",
                    scale=2,
                )
            gloss_in = gr.Textbox(
                label="gloss（言語学グロス）",
                placeholder="例: 水（water）",
            )
            usage_in = gr.Textbox(
                label="usage（用例）",
                placeholder="例: mataru zanum — 我（要）水。",
                lines=2,
            )

            with gr.Accordion(
                "手動オーバーライド（旧 slug / カスタム TTS）",
                open=False,
            ):
                slug_in = gr.Textbox(
                    label="slug を手動指定（省略可）",
                    placeholder="例: kasul_ija_m_l_asl_aseq",
                )
                tts_in = gr.Textbox(
                    label="tts を手動指定（省略可）",
                    placeholder="例: m:akawas [[i,t,a,=]], m:au, [[b:a,s,ai,=]]",
                )

            dry_in = gr.Radio(
                choices=[
                    ("Dry run（テスト送信・コミットしない）", True),
                    ("本コミット（GitHub に push）", False),
                ],
                value=True,
                label="送信モード",
                elem_classes=["dry-mode-radio"],
            )
            with gr.Row(elem_classes=["controls-row"]):
                preview_btn = gr.Button("派生プレビュー", variant="secondary")
                submit_btn = gr.Button("送信", variant="primary")

            with gr.Row():
                p_display = gr.Textbox(label="display", interactive=False)
                p_slug = gr.Textbox(label="slug", interactive=False)
                p_tts = gr.Textbox(label="tts", interactive=False)

            status_out = gr.Markdown(elem_classes=["status-box"])
            with gr.Row():
                ipay_audio = gr.Audio(label="IPay (bsy)", interactive=False)
                hok_audio = gr.Audio(label="台語 (bsystd)", interactive=False)

        gr.HTML(
            f"<p class='hint'>"
            f"対象: <code>{GH_OWNER}/{GH_REPO}</code> "
            f"(<code>{GH_BRANCH}</code>) ｜ "
            f"daily.json: <code>{DAILY_JSON_PATH}</code><br>"
            f"iPhone Safari → 共有 → ホーム画面に追加で PWA 風に常駐できます。"
            f"</p>"
        )

        preview_btn.click(
            _preview_fn,
            inputs=[word_in, slug_in, tts_in],
            outputs=[p_display, p_slug, p_tts],
        )
        submit_btn.click(
            submit_fn,
            inputs=[token_in, date_in, word_in, gloss_in, usage_in,
                    slug_in, tts_in, dry_in],
            outputs=[status_out, ipay_audio, hok_audio],
        )
