"""blog_post.py — basay.tw 研究筆記（blog）投稿フォーム.

Gradio Blocks。iPhone Safari 等から Markdown で記事を投稿できる。

機能:
  1. Markdown 本文を HTML に変換
  2. blog/posts.json に新規エントリを追加（既存 slug の場合は更新）
  3. blog/{slug}/index.html を生成
  4. blog/index.html を再生成（記事一覧・タグクラウド・最近記事）
  5. sitemap.xml を再生成（static + blog posts 全網羅）
  6. 写真（最大3枚）を blog/{slug}/img1.jpg〜img3.jpg として同梱
     - 1600px max にリサイズ、JPEG q90 で再圧縮
     - Markdown 本文中で ![説明](img1.jpg) のように参照
  7. これら一括で ctotsai-hub/basay-tw に直接コミット

認証:
  daily_updater と共通の SUBMIT_TOKEN（Space Secrets）を使用。
  GITHUB_TOKEN（contents:write 権限の PAT）も共通。

URL ゲート:
  iframe 表示時、URL に `blog` を含む場合（例: ?blog, #blog）のみフォームを表示。
  一般公開では非表示（CSS + img onerror で発火）。
"""

from __future__ import annotations

import datetime as dt
import hmac
import io
import json
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any

import gradio as gr
import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# iPhone の HEIC を PIL で開けるようにする（pillow-heif がインストールされていれば）
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HAS_HEIF = True
except ImportError:
    _HAS_HEIF = False

from github_client import GitHubClient, GitHubError

log = logging.getLogger("basay.blog_post")

# ----------------------------------------------------------------- env ---

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
SUBMIT_TOKEN = os.environ.get("SUBMIT_TOKEN", "")
GH_OWNER = os.environ.get("BASAY_GH_OWNER", "ctotsai-hub")
GH_REPO = os.environ.get("BASAY_GH_REPO", "basay-tw")
GH_BRANCH = os.environ.get("BASAY_GH_BRANCH", "main")
POSTS_JSON_PATH = os.environ.get("BASAY_POSTS_JSON", "blog/posts.json")
SITEMAP_PATH = os.environ.get("BASAY_SITEMAP", "sitemap.xml")
SITE_URL = os.environ.get("BASAY_SITE_URL", "https://basay.tw")

# Image processing settings
IMG_MAX_DIM = int(os.environ.get("BASAY_IMG_MAX_DIM", "1600"))
IMG_QUALITY = int(os.environ.get("BASAY_IMG_QUALITY", "90"))
MAX_IMAGES = 3

# Static pages for sitemap (path, lastmod hint or None = use today)
STATIC_PAGES = [
    ("/",                                None),
    ("/about/",                          None),
    ("/blog/",                           None),
    ("/dictionary/",                     None),
    ("/education/",                      None),
    ("/grammar/",                        None),
    ("/research/",                       None),
    ("/research/2026-04-basay-acoustic/", None),
    ("/hf-space-tts/",                   None),
]

# ------------------------------------------------------------- jinja2 ---

TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)

MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


# ----------------------------------------------------------- helpers ---

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _today_iso() -> str:
    tz = dt.timezone(dt.timedelta(hours=8))
    return dt.datetime.now(tz).date().isoformat()


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not slug:
        raise ValueError("slug を入力してください（URL 用、半角英数とハイフン）")
    if not _SLUG_PATTERN.match(slug):
        raise ValueError(f"slug は半角英数とハイフンのみ: {slug!r}")
    return slug


def _validate_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat((s or "").strip())
    except ValueError as e:
        raise ValueError(f"日付は YYYY-MM-DD 形式: {e}") from e


def _authenticate(token: str) -> None:
    if not SUBMIT_TOKEN:
        raise RuntimeError(
            "サーバ側に SUBMIT_TOKEN が未設定です。Space Secrets に登録してください。"
        )
    if not hmac.compare_digest(token or "", SUBMIT_TOKEN):
        raise PermissionError("認証トークンが一致しません。")


def _ensure_github_token() -> str:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN 未設定。Space Secrets に PAT を登録してください。")
    return GITHUB_TOKEN


def _parse_tags(s: str) -> list[str]:
    if not s:
        return []
    return [t.strip() for t in re.split(r"[,，、]", s) if t.strip()]


def _make_excerpt(body_html: str, max_chars: int = 140) -> str:
    """body_html から最初の <p> のテキストを抽出して短縮."""
    m = re.search(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL)
    if not m:
        text = re.sub(r"<[^>]+>", "", body_html)
    else:
        text = re.sub(r"<[^>]+>", "", m.group(1))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def _build_toc(body_html: str) -> list[dict[str, Any]]:
    """h2/h3 から目次を組み立てる.

    python-markdown の toc 拡張が自動付与した id="..." を抽出して
    TOC リンクと一致させる（日本語/中国語見出しでも `_1`, `_2` のような
    自動 id が付くので、そのまま使う）。
    """
    items: list[dict[str, Any]] = []
    for m in re.finditer(r'<h([23])\s*([^>]*)>(.*?)</h\1>', body_html, re.DOTALL):
        level = int(m.group(1))
        attrs = m.group(2)
        text = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        id_m = re.search(r'id="([^"]+)"', attrs)
        if id_m:
            hid = id_m.group(1)
        else:
            # 念のためのフォールバック（toc 拡張が無効でも動く）
            hid = re.sub(r"[^\w-]+", "-", text).strip("-").lower() or f"h{len(items)}"
        items.append({"id": hid, "level": level, "text": text})
    return items


def _date_display(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def _date_short(d: dt.date) -> str:
    return f"{d.year}.{d.month:02d}"


def _post_for_index(p: dict[str, Any]) -> dict[str, Any]:
    d = dt.date.fromisoformat(p["date"])
    return {
        **p,
        "day": f"{d.day:02d}",
        "year": str(d.year),
        "month_abbr": MONTH_ABBR[d.month],
        "date_short": _date_short(d),
    }


def _aggregate_tags(posts: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for p in posts:
        for t in (p.get("tags") or []) + (p.get("tags_special") or []):
            if t not in seen:
                seen.append(t)
    return seen


# ---------------------------------------------------------- images ---

def _process_image(file_obj: Any, max_dim: int = IMG_MAX_DIM,
                   quality: int = IMG_QUALITY) -> bytes:
    """画像をリサイズ＋JPEG 再エンコード. file_obj は Gradio File or filepath."""
    if not _HAS_PIL:
        raise RuntimeError("Pillow がインストールされていません。requirements.txt に pillow を追加してください。")
    if hasattr(file_obj, "name"):
        path = file_obj.name
    else:
        path = str(file_obj)
    img = Image.open(path)
    # EXIF orientation 補正
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    # RGB に変換（PNG の alpha や RGBA は捨てる）
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            bg.paste(img, mask=img.split()[3])
        else:
            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
        img = bg
    elif img.mode == "L":
        img = img.convert("RGB")
    # リサイズ（縦横どちらか長い方を max_dim に）
    w, h = img.size
    longest = max(w, h)
    if longest > max_dim:
        scale = max_dim / longest
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
    # JPEG 出力
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


# ---------------------------------------------------------- renderers ---

def render_article_html(entry: dict[str, Any], body_md: str) -> str:
    converter = md.Markdown(
        extensions=["extra", "tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False}},
    )
    body_html = converter.convert(body_md or "")

    d = dt.date.fromisoformat(entry["date"])
    excerpt = entry.get("excerpt") or _make_excerpt(body_html)
    ctx = {
        "slug": entry["slug"],
        "title": entry["title"],
        "subtitle": entry.get("subtitle", ""),
        "tags": entry.get("tags", []),
        "tags_special": entry.get("tags_special", []),
        "dialect": entry.get("dialect", ""),
        "date": entry["date"],
        "date_display": _date_display(d),
        "reading_time": entry.get("reading_time", ""),
        "excerpt": excerpt,
        "body_html": body_html,
        "toc_items": _build_toc(body_html),
    }
    tpl = _env.get_template("blog_article.html.j2")
    return tpl.render(**ctx)


def render_index_html(posts: list[dict[str, Any]]) -> str:
    indexed = [_post_for_index(p) for p in posts]
    recent = indexed[:5]
    tags = _aggregate_tags(posts)
    tpl = _env.get_template("blog_index.html.j2")
    return tpl.render(posts=indexed, recent_posts=recent, all_tags=tags)


def render_sitemap_xml(posts: list[dict[str, Any]]) -> str:
    """sitemap.xml を生成. STATIC_PAGES + 全 blog 投稿."""
    today = _today_iso()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    # static
    for path, lastmod in STATIC_PAGES:
        lm = lastmod or today
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_URL}{path}</loc>")
        lines.append(f"    <lastmod>{lm}</lastmod>")
        lines.append("  </url>")
    # blog (date 昇順 / 降順どちらでも検索エンジン的に同じ)
    for p in sorted(posts, key=lambda x: x.get("date", ""), reverse=True):
        slug = p.get("slug")
        if not slug:
            continue
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_URL}/blog/{slug}/</loc>")
        lines.append(f"    <lastmod>{p.get('date', today)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    lines.append("")  # trailing newline
    return "\n".join(lines)


# ----------------------------------------------------------- submit ---

def submit(
    token: str,
    slug_in: str,
    title: str,
    subtitle: str,
    date_str: str,
    reading_time: str,
    tags_str: str,
    tags_special_str: str,
    dialect: str,
    body_md: str,
    images: list[Any] | None,
    dry_run: bool,
) -> tuple[str, str | None]:
    try:
        _authenticate(token)
        slug = _validate_slug(slug_in)
        title = (title or "").strip()
        if not title:
            raise ValueError("タイトルを入力してください。")
        body_md = (body_md or "").strip()
        if not body_md:
            raise ValueError("本文（Markdown）を入力してください。")

        d = _validate_date(date_str)
        rtime = (reading_time or "").strip() or "約 5 分鐘"

        entry: dict[str, Any] = {
            "slug": slug,
            "title": title,
            "subtitle": (subtitle or "").strip(),
            "date": d.isoformat(),
            "reading_time": rtime,
            "tags": _parse_tags(tags_str),
            "tags_special": _parse_tags(tags_special_str),
            "dialect": (dialect or "").strip(),
        }

        # 画像処理（最大 MAX_IMAGES 枚、JPEG 化）
        image_blobs: list[tuple[str, bytes]] = []  # (filename, bytes)
        if images:
            usable = [im for im in images if im is not None][:MAX_IMAGES]
            for i, im in enumerate(usable, start=1):
                fname = f"img{i}.jpg"
                try:
                    blob = _process_image(im)
                except Exception as e:
                    raise ValueError(f"画像 {i} の処理に失敗: {e}") from e
                image_blobs.append((fname, blob))

        article_html = render_article_html(entry, body_md)
        entry["excerpt"] = _make_excerpt(article_html)

        if dry_run:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                prefix=f"preview_{slug}_", suffix=".html", delete=False, mode="w",
                encoding="utf-8",
            )
            tmp.write(article_html)
            tmp.close()
            img_info = ""
            if image_blobs:
                img_info = "\n\n**処理後の画像（dry run）**\n"
                for fname, blob in image_blobs:
                    img_info += f"- `{fname}`: {len(blob):,} bytes\n"
            status = (
                f"### ✅ Dry run 成功（コミットなし）\n\n"
                f"- slug: `{slug}`\n"
                f"- title: {title}\n"
                f"- date: {entry['date']}\n"
                f"- tags: {entry['tags']}\n"
                f"- excerpt: {entry['excerpt']}\n"
                f"{img_info}\n"
                f"プレビュー HTML がダウンロードできます。\n"
                f"Dry run を外して再送信すると GitHub に commit します。"
            )
            return status, tmp.name

        # --- GitHub 操作 ---
        gh = GitHubClient(
            token=_ensure_github_token(),
            owner=GH_OWNER, repo=GH_REPO, branch=GH_BRANCH,
            author_name="basay-blog-poster",
            author_email="basay-blog-poster@users.noreply.github.com",
        )

        # 1) posts.json 読み込み（無ければ空）
        raw, posts_sha = gh.get_file(POSTS_JSON_PATH)
        if raw:
            posts_data = json.loads(raw.decode("utf-8"))
        else:
            posts_data = {"posts": []}
        posts: list[dict[str, Any]] = posts_data.get("posts", [])

        # 同じ slug があれば置換、なければ追加。常に date 降順に並べる。
        posts = [p for p in posts if p.get("slug") != slug]
        posts.append(entry)
        posts.sort(key=lambda p: p.get("date", ""), reverse=True)
        posts_data["posts"] = posts

        results: list[tuple[str, dict[str, Any]]] = []

        # 2) 画像コミット（先に画像、後に HTML が参照できるよう）
        for fname, blob in image_blobs:
            img_path = f"blog/{slug}/{fname}"
            r = gh.put_file(
                img_path, blob,
                f"blog: image {slug}/{fname} ({len(blob):,}B)",
            )
            results.append((img_path, r))

        # 3) 記事 HTML
        article_path = f"blog/{slug}/index.html"
        r = gh.put_file(
            article_path,
            article_html.encode("utf-8"),
            f"blog: post {slug} — {title}",
        )
        results.append((article_path, r))

        # 4) 一覧 HTML（再生成）
        index_html = render_index_html(posts)
        r = gh.put_file(
            "blog/index.html",
            index_html.encode("utf-8"),
            f"blog: rebuild index ({len(posts)} posts)",
        )
        results.append(("blog/index.html", r))

        # 5) sitemap.xml （再生成）
        sitemap_xml = render_sitemap_xml(posts)
        r = gh.put_file(
            SITEMAP_PATH,
            sitemap_xml.encode("utf-8"),
            f"site: regenerate sitemap.xml ({len(STATIC_PAGES)} static + {len(posts)} posts)",
        )
        results.append((SITEMAP_PATH, r))

        # 6) posts.json
        posts_json_body = json.dumps(posts_data, ensure_ascii=False, indent=2) + "\n"
        r = gh.put_file(
            POSTS_JSON_PATH,
            posts_json_body.encode("utf-8"),
            f"blog: update posts.json ({slug})",
            sha=posts_sha or None,
        )
        results.append((POSTS_JSON_PATH, r))

        def short_sha(rr: dict[str, Any]) -> str:
            sha = (rr.get("commit") or {}).get("sha", "")
            return sha[:7] if sha else ("skipped" if rr.get("skipped") else "?")

        url = f"{SITE_URL}/blog/{slug}/"
        rows = "\n".join(f"| `{path}` | {short_sha(r)} |" for path, r in results)
        status = (
            f"### ✅ 投稿成功\n\n"
            f"- **URL**: [{url}]({url})\n"
            f"- **タイトル**: {title}\n"
            f"- **画像**: {len(image_blobs)} 枚\n\n"
            f"| ファイル | 結果 |\n|---|---|\n"
            f"{rows}\n\n"
            f"GitHub Pages の反映は 30〜120 秒。"
        )
        return status, None

    except (PermissionError, ValueError, RuntimeError, GitHubError) as e:
        return f"### ❌ エラー\n\n```\n{type(e).__name__}: {e}\n```", None
    except Exception:
        log.exception("unexpected error in blog submit")
        return f"### ❌ 予期せぬエラー\n\n```\n{traceback.format_exc()}\n```", None


# ------------------------------------------------------------ UI ---

CSS = """
#blog-poster-root {max-width: 760px; margin: 0 auto;}
#blog-poster-root .gr-button-primary {min-height: 48px; font-size: 1.05em;}
#blog-poster-root .gr-text-input input,
#blog-poster-root textarea {font-size: 16px;}
#blog-poster-root .markdown-hint {
  font-size: 0.85em; color: #6a6055; background: #fdfaf5;
  border: 1px solid #d4c9b8; border-radius: 4px;
  padding: 10px 14px; margin: 4px 0 8px;
}
"""

MARKDOWN_HINT = """
**Markdown 記法ガイド**
- 見出し: `## 大見出し` / `### 小見出し`
- 強調: `**太字**` / `*斜体*`
- リンク: `[文字](URL)`
- リスト: `- 項目` / `1. 番号`
- 引用: `> 引用文`
- コード: `` `inline` `` / 行頭に三連バッククォート
- 表: `| 列1 | 列2 |` の行と `| --- | --- |` の区切り
- **画像**: `![説明](img1.jpg)` `![説明](img2.jpg)` `![説明](img3.jpg)` の3つまで（下から添付）
- 巴賽語の単語は HTML タグ `<span class="basay">lalaleona</span>` で強調可能
"""


_URL_GATE_HTML = """
<style>
#blog-poster-root { display: none !important; }
body.basay-blog-on #blog-poster-root { display: block !important; }
</style>
<img src="x" alt="" style="display:none"
     onerror="this.remove();(function(){
       function isBlogUrl(){
         var loc=window.location;
         return loc.pathname.toLowerCase().indexOf('blog')!==-1
             || loc.search.toLowerCase().indexOf('blog')!==-1
             || loc.hash.toLowerCase().indexOf('blog')!==-1;
       }
       function apply(){ document.body.classList.toggle('basay-blog-on', isBlogUrl()); }
       apply();
       var n=0; var t=setInterval(function(){ apply(); if(++n>40) clearInterval(t); }, 200);
       window.addEventListener('hashchange', apply);
       window.addEventListener('popstate', apply);
     })()">
"""


def _build_form() -> None:
    gr.HTML(_URL_GATE_HTML)
    with gr.Column(elem_id="blog-poster-root"):
        gr.Markdown(
            "## 研究筆記 — Blog Poster\n"
            "Markdown で記事を書いて送信すると、`blog/{slug}/index.html`、`blog/index.html`、"
            "`blog/posts.json`、`sitemap.xml`、添付画像 が自動コミットされます。\n"
            "**Dry run** をオンにすると、commit せずプレビュー HTML を生成して確認できます。"
        )

        with gr.Row():
            token_in = gr.Textbox(
                label="認証トークン",
                placeholder="Space Secrets の SUBMIT_TOKEN と同じもの",
                type="password",
            )
            date_in = gr.Textbox(
                label="日付 (YYYY-MM-DD)",
                value=_today_iso(),
            )

        with gr.Row():
            slug_in = gr.Textbox(
                label="slug（URL用 / 半角英数とハイフン）",
                placeholder="例: puta-puti-etymology",
            )
            reading_time_in = gr.Textbox(
                label="読了時間",
                value="約 8 分鐘",
            )

        title_in = gr.Textbox(
            label="タイトル",
            placeholder="例: puta / puti 的西班牙語借詞考",
        )
        subtitle_in = gr.Textbox(
            label="サブタイトル（任意）",
            placeholder="例: 以語言向量理論2.0分析西班牙語借詞的音韻適應。",
            lines=2,
        )

        with gr.Row():
            tags_in = gr.Textbox(
                label="タグ（カンマ区切り）",
                placeholder="例: 音韻研究, 詞源考察",
            )
            tags_special_in = gr.Textbox(
                label="特殊タグ（赤色／カンマ区切り、任意）",
                placeholder="例: 哆囉美遠方言",
            )
        dialect_in = gr.Textbox(
            label="方言／領域（任意）",
            placeholder="例: Trobiawan",
        )

        gr.Markdown(MARKDOWN_HINT, elem_classes=["markdown-hint"])
        body_in = gr.Textbox(
            label="本文（Markdown）",
            placeholder="## 問題の所在\n\nここに本文を書く...\n\n![田野照片](img1.jpg)",
            lines=18,
        )

        images_in = gr.Files(
            label=f"添付画像（最大 {MAX_IMAGES} 枚、HEIC/JPEG/PNG 対応、自動で {IMG_MAX_DIM}px max・JPEG q{IMG_QUALITY} に変換）",
            file_count="multiple",
            file_types=["image", ".heic", ".heif", ".HEIC", ".HEIF"],
        )

        dry_in = gr.Checkbox(
            value=True,
            label="Dry run（コミットせず生成だけ確認）",
        )
        submit_btn = gr.Button("送信", variant="primary")

        status_out = gr.Markdown()
        preview_file = gr.File(label="プレビュー HTML（Dry run のみ）")

        submit_btn.click(
            submit,
            inputs=[token_in, slug_in, title_in, subtitle_in, date_in,
                    reading_time_in, tags_in, tags_special_in, dialect_in,
                    body_in, images_in, dry_in],
            outputs=[status_out, preview_file],
        )

        gr.Markdown(
            "---\n"
            f"- 対象リポジトリ：`{GH_OWNER}/{GH_REPO}` (`{GH_BRANCH}`)\n"
            f"- posts.json：`{POSTS_JSON_PATH}`\n"
            f"- sitemap：`{SITEMAP_PATH}`（毎回再生成）\n"
            "- 画像はリサイズ後 `blog/{slug}/img1.jpg` 等に同梱、Markdown で `![](img1.jpg)` 参照。\n"
            "- 同じ slug を再送信すると既存記事を**上書き**します。"
        )


def build_blog_section() -> None:
    """既存 gr.Blocks コンテキストにそのまま埋め込む用. URL に 'blog' を含む時のみ表示."""
    _build_form()


def build_blocks() -> gr.Blocks:
    """スタンドアロン用. 自前で gr.Blocks をラップして返す."""
    with gr.Blocks(css=CSS, title="basay.tw blog poster") as blocks:
        _build_form()
    return blocks


def launch() -> None:
    logging.basicConfig(level=logging.INFO)
    build_blocks().queue().launch()


if __name__ == "__main__":
    launch()
