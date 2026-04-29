"""Publish the generated changelog to GitHub releases and optionally CHANGELOG.md."""

from __future__ import annotations

import logging

from changelog.config import Config
from changelog.github_client import GitHubClient

log = logging.getLogger("ai-changelog-generator")


class Publisher:
    """Publish changelog to GitHub release body and optionally commit CHANGELOG.md."""

    def __init__(self, *, github: GitHubClient, cfg: Config) -> None:
        self._github = github
        self._cfg = cfg

    def publish(self, *, changelog_body: str, release_tag: str) -> None:
        """Update the release body, and optionally prepend to CHANGELOG.md."""
        if self._cfg.release_id:
            log.info("Updating release %s body.", self._cfg.release_id)
            self._github.update_release_body(self._cfg.release_id, changelog_body)
        else:
            log.info("No release ID — finding or creating release for tag %s.", release_tag)
            self._github.get_or_create_release_by_tag(release_tag, changelog_body)

        if self._cfg.update_changelog_file:
            self._update_changelog_file(changelog_body, release_tag)

    def _update_changelog_file(self, changelog_body: str, release_tag: str) -> None:
        """Prepend the new changelog section to CHANGELOG.md and commit."""
        path = self._cfg.changelog_file_path
        try:
            existing_content, sha = self._github.get_file_contents(path)
            new_content = (
                f"{changelog_body}\n\n{existing_content}" if existing_content else changelog_body
            )
            commit_sha = sha if sha else None
            self._github.update_file_contents(
                path,
                new_content,
                commit_sha,
                message=f"chore: update {path} for {release_tag} [skip ci]",
            )
            log.info("Committed %s for %s.", path, release_tag)
        except Exception:
            log.warning(
                "Failed to update %s — release body was already published.", path, exc_info=True
            )
