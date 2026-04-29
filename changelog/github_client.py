"""GitHub REST API client for fetching tags, commits, PRs and publishing releases."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from changelog.exceptions import GitHubAPIError

log = logging.getLogger("ai-changelog-generator")

API_BASE = "https://api.github.com"
USER_AGENT = "ai-changelog-generator/1.0"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_BASE = 1


@dataclass
class CommitInfo:
    """Structured commit data from the GitHub API."""

    sha: str
    message: str
    author: str
    url: str


@dataclass
class PRInfo:
    """Structured pull request data from the GitHub API."""

    number: int
    title: str
    body: str
    labels: list[str]
    url: str
    author: str


def _parse_commit(raw: dict[str, Any]) -> CommitInfo:
    """Extract CommitInfo from a raw GitHub API commit object."""
    commit_obj: dict[str, Any] = raw.get("commit", {})
    author_obj: dict[str, Any] = raw.get("author") or {}
    return CommitInfo(
        sha=raw.get("sha", ""),
        message=commit_obj.get("message", ""),
        author=author_obj.get("login", "unknown"),
        url=raw.get("html_url", ""),
    )


@dataclass
class GitHubClient:
    """Client for GitHub REST API operations required by the changelog pipeline."""

    token: str
    repo: str
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            }
        )

    def get_previous_tag(self, current_tag: str) -> str | None:
        """Return the tag immediately before *current_tag*, or None for first release."""
        page = 1
        found_current = False
        while True:
            data: list[dict[str, Any]] = self._get_list(
                f"/repos/{self.repo}/tags", params={"per_page": 100, "page": page}
            )
            if not data:
                break
            for tag in data:
                name: str = tag["name"]
                if found_current:
                    return name
                if name == current_tag:
                    found_current = True
            page += 1
        return None

    def get_commits_between(
        self,
        base: str | None,
        head: str,
        *,
        max_commits: int,
    ) -> list[CommitInfo]:
        """Fetch commits between two refs. Uses list endpoint when *base* is None."""
        if base is None:
            data = self._get_list(
                f"/repos/{self.repo}/commits",
                params={"sha": head, "per_page": min(max_commits, 100)},
            )
            return [_parse_commit(c) for c in data[:max_commits]]

        compare = self._get_dict(f"/repos/{self.repo}/compare/{base}...{head}")
        commits: list[dict[str, Any]] = compare.get("commits", [])
        return [_parse_commit(c) for c in commits[:max_commits]]

    def get_merged_prs(
        self,
        base: str | None,
        head: str,
        *,
        max_prs: int,
    ) -> list[PRInfo]:
        """Find merged PRs associated with commits in the range."""
        if base is None:
            commits_data = self._get_list(
                f"/repos/{self.repo}/commits",
                params={"sha": head, "per_page": 100},
            )
        else:
            compare = self._get_dict(f"/repos/{self.repo}/compare/{base}...{head}")
            commits_data = compare.get("commits", [])

        seen_pr_numbers: set[int] = set()
        prs: list[PRInfo] = []

        for commit in commits_data:
            sha: str = commit["sha"]
            associated = self._get_list(f"/repos/{self.repo}/commits/{sha}/pulls")
            for pr_data in associated:
                pr_number: int = pr_data["number"]
                if pr_number in seen_pr_numbers:
                    continue
                if pr_data.get("merged_at") is None:
                    continue
                seen_pr_numbers.add(pr_number)
                labels_raw: list[dict[str, Any]] = pr_data.get("labels", [])
                user_data: dict[str, Any] = pr_data.get("user", {})
                prs.append(
                    PRInfo(
                        number=pr_number,
                        title=pr_data.get("title", ""),
                        body=pr_data.get("body", "") or "",
                        labels=[lb["name"] for lb in labels_raw],
                        url=pr_data.get("html_url", ""),
                        author=user_data.get("login", "unknown"),
                    )
                )
                if len(prs) >= max_prs:
                    return prs

        return prs

    def update_release_body(self, release_id: str, body: str) -> None:
        """Update an existing GitHub release body."""
        self._request(
            "PATCH", f"/repos/{self.repo}/releases/{release_id}", json_data={"body": body}
        )

    def get_or_create_release_by_tag(self, tag: str, body: str) -> None:
        """Find a release by tag and update it, or create a new one."""
        try:
            data = self._get_dict(f"/repos/{self.repo}/releases/tags/{tag}")
            release_id = str(data["id"])
            self.update_release_body(release_id, body)
        except GitHubAPIError as exc:
            if "404" not in exc.message:
                raise
            self._request(
                "POST",
                f"/repos/{self.repo}/releases",
                json_data={"tag_name": tag, "name": tag, "body": body},
            )

    def get_file_contents(self, path: str) -> tuple[str, str]:
        """Return (decoded_content, sha) for a file, or ("", "") if not found."""
        try:
            data = self._get_dict(f"/repos/{self.repo}/contents/{path}")
        except GitHubAPIError as exc:
            if "404" not in exc.message:
                raise
            return ("", "")
        content_b64: str = data.get("content", "")
        sha: str = data.get("sha", "")
        decoded = base64.b64decode(content_b64).decode("utf-8") if content_b64 else ""
        return (decoded, sha)

    def update_file_contents(
        self,
        path: str,
        content: str,
        sha: str | None,
        message: str,
    ) -> None:
        """Create or update a file via the Contents API."""
        payload: dict[str, str] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        self._request("PUT", f"/repos/{self.repo}/contents/{path}", json_data=payload)

    def _get_dict(self, path: str, *, params: dict[str, int | str] | None = None) -> dict[str, Any]:
        result = self._request("GET", path, params=params)
        if not isinstance(result, dict):
            raise GitHubAPIError("GITHUB_API_ERROR", f"Expected dict from {path}, got list")
        return result

    def _get_list(
        self, path: str, *, params: dict[str, int | str] | None = None
    ) -> list[dict[str, Any]]:
        result = self._request("GET", path, params=params)
        if not isinstance(result, list):
            raise GitHubAPIError("GITHUB_API_ERROR", f"Expected list from {path}, got dict")
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int | str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Execute an HTTP request with retry and error handling."""
        url = f"{API_BASE}{path}"
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.request(
                    method, url, params=params, json=json_data, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Request to %s failed (attempt %d): %s", url, attempt + 1, exc)
                time.sleep(BACKOFF_BASE * (2**attempt))
                continue

            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                reset_at = resp.headers.get("X-RateLimit-Reset", "unknown")
                raise GitHubAPIError(
                    "RATE_LIMITED",
                    f"GitHub rate limit exceeded. Resets at {reset_at}",
                )

            if resp.status_code >= 500:
                last_exc = GitHubAPIError(
                    "GITHUB_API_ERROR",
                    f"{method} {path} returned {resp.status_code}",
                )
                log.warning("GitHub API %d on %s (attempt %d)", resp.status_code, path, attempt + 1)
                time.sleep(BACKOFF_BASE * (2**attempt))
                continue

            if resp.status_code >= 400:
                raise GitHubAPIError(
                    "GITHUB_API_ERROR",
                    f"{method} {path} returned {resp.status_code}: {resp.text[:200]}",
                )

            return resp.json()  # type: ignore[no-any-return]

        raise GitHubAPIError(
            "GITHUB_API_ERROR",
            f"All {MAX_RETRIES} retries exhausted for {method} {path}",
        ) from last_exc
