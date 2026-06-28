"""github_client.py — GitHub REST API ラッパー（contents 操作専用）.

`requests` のみに依存する薄いラッパー。PyGitHub よりも軽量で、Space 起動も速い。

ctotsai-hub/basay-tw リポに対して次の操作を行う：
  - data/daily.json を読み・書き
  - 任意のバイナリ（wav）を base64 でコミット

すべて mainブランチに直接 commit する想定。
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger("basay.github_client")

GITHUB_API = "https://api.github.com"
DEFAULT_BRANCH = "main"


# --------------------------------------------------------------- errors ---

class GitHubError(RuntimeError):
    """GitHub API がエラーを返した時に投げる."""

    def __init__(self, status: int, body: str | dict):
        super().__init__(f"GitHub API {status}: {body}")
        self.status = status
        self.body = body


# --------------------------------------------------------------- client ---

@dataclass
class GitHubClient:
    """ctotsai-hub/basay-tw 専用のミニマル GitHub クライアント."""

    token: str
    owner: str = "ctotsai-hub"
    repo: str = "basay-tw"
    branch: str = DEFAULT_BRANCH
    author_name: str = "basay-daily-updater"
    author_email: str = "basay-daily-updater@users.noreply.github.com"
    timeout: float = 30.0

    # ---- internal --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "basay-daily-updater/1.0",
        }

    def _url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kw: Any) -> requests.Response:
        url = self._url(path)
        resp = requests.request(method, url, headers=self._headers(),
                                timeout=self.timeout, **kw)
        if resp.status_code >= 400:
            try:
                body: Any = resp.json()
            except ValueError:
                body = resp.text
            raise GitHubError(resp.status_code, body)
        return resp

    # ---- contents -------------------------------------------------------

    def get_file(self, path: str) -> tuple[bytes, str]:
        """ファイル内容と sha を返す. 404 の場合は (b"", "")."""
        params = {"ref": self.branch}
        try:
            resp = self._request("GET", f"contents/{path}", params=params)
        except GitHubError as e:
            if e.status == 404:
                return b"", ""
            raise
        data = resp.json()
        content_b64 = data.get("content", "")
        decoded = base64.b64decode(content_b64) if content_b64 else b""
        return decoded, data.get("sha", "")

    def put_file(
        self,
        path: str,
        content: bytes,
        message: str,
        *,
        sha: str | None = None,
    ) -> dict[str, Any]:
        """ファイルを新規作成 or 更新.

        - 既存 sha は省略可（その場合は自動で取得）。
        - 同一内容ならスキップ。
        """
        if sha is None:
            _, sha = self.get_file(path)

        if sha:
            existing, _ = self.get_file(path)
            if existing == content:
                log.info("Skip put_file: %s (no change)", path)
                return {"path": path, "skipped": True}

        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
            "committer": {"name": self.author_name, "email": self.author_email},
            "author": {"name": self.author_name, "email": self.author_email},
        }
        if sha:
            payload["sha"] = sha

        resp = self._request("PUT", f"contents/{path}", json=payload)
        return resp.json()

    # ---- daily.json helpers --------------------------------------------

    def load_daily(self, path: str = "data/daily.json") -> tuple[dict[str, Any], str]:
        """daily.json をロードする. 存在しなければ空 dict と空 sha."""
        raw, sha = self.get_file(path)
        if not raw:
            return {}, ""
        try:
            return json.loads(raw.decode("utf-8")), sha
        except json.JSONDecodeError as e:
            raise GitHubError(200, f"daily.json is not valid JSON: {e}")

    def update_daily_entry(
        self,
        date_key: str,
        entry: dict[str, Any],
        *,
        path: str = "data/daily.json",
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        """daily.json の `date_key` を `entry` で更新（既存があれば上書き）."""
        daily, sha = self.load_daily(path)
        daily[date_key] = entry
        # 安定した順序で書き出す: default を先頭に置き、それ以外は日付昇順
        ordered: dict[str, Any] = {}
        if "default" in daily:
            ordered["default"] = daily["default"]
        for key in sorted(k for k in daily if k != "default"):
            ordered[key] = daily[key]
        body = json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
        msg = commit_message or f"Daily: {date_key} {entry.get('word', '').strip()}".rstrip()
        return self.put_file(path, body.encode("utf-8"), msg, sha=sha)

    def put_audio(
        self,
        repo_path: str,
        wav_bytes: bytes,
        commit_message: str,
    ) -> dict[str, Any]:
        """音声ファイル（wav バイト列）をコミット."""
        return self.put_file(repo_path, wav_bytes, commit_message)


# -------------------------------------------------------------- helpers ---

def build_audio_repo_path(slug: str, voice: str) -> str:
    """`voice` は "ipay" or "hokkien"."""
    if voice not in {"ipay", "hokkien"}:
        raise ValueError(f"voice must be 'ipay' or 'hokkien', got {voice!r}")
    return f"education/phrasebook/audio/{voice}/{slug}.wav"
