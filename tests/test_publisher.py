"""Tests for changelog.publisher."""

from __future__ import annotations

from unittest.mock import MagicMock

from changelog.publisher import Publisher


def _make_publisher(
    release_id: str = "12345",
    update_changelog_file: bool = False,
    changelog_file_path: str = "CHANGELOG.md",
) -> tuple[Publisher, MagicMock]:
    github = MagicMock()
    cfg = MagicMock()
    cfg.release_id = release_id
    cfg.update_changelog_file = update_changelog_file
    cfg.changelog_file_path = changelog_file_path
    publisher = Publisher(github=github, cfg=cfg)
    return publisher, github


class TestPublisher:
    def test_updates_release_body_when_release_id_set(self) -> None:
        publisher, github = _make_publisher(release_id="42")
        publisher.publish(changelog_body="body", release_tag="v1.0.0")
        github.update_release_body.assert_called_once_with("42", "body")

    def test_creates_release_when_release_id_empty(self) -> None:
        publisher, github = _make_publisher(release_id="")
        publisher.publish(changelog_body="body", release_tag="v1.0.0")
        github.get_or_create_release_by_tag.assert_called_once_with("v1.0.0", "body")
        github.update_release_body.assert_not_called()

    def test_commits_changelog_when_enabled(self) -> None:
        publisher, github = _make_publisher(update_changelog_file=True)
        github.get_file_contents.return_value = ("old content", "sha123")
        publisher.publish(changelog_body="new body", release_tag="v1.0.0")
        github.update_file_contents.assert_called_once()
        call_args = github.update_file_contents.call_args
        assert "new body" in call_args[0][1]
        assert "old content" in call_args[0][1]

    def test_skips_changelog_when_disabled(self) -> None:
        publisher, github = _make_publisher(update_changelog_file=False)
        publisher.publish(changelog_body="body", release_tag="v1.0.0")
        github.get_file_contents.assert_not_called()
        github.update_file_contents.assert_not_called()

    def test_changelog_commit_includes_skip_ci(self) -> None:
        publisher, github = _make_publisher(update_changelog_file=True)
        github.get_file_contents.return_value = ("", "")
        publisher.publish(changelog_body="body", release_tag="v1.0.0")
        call_args = github.update_file_contents.call_args
        commit_message = call_args.kwargs.get(
            "message", call_args[0][3] if len(call_args[0]) > 3 else ""
        )
        assert "[skip ci]" in commit_message

    def test_changelog_failure_logs_warning_does_not_abort(self) -> None:
        publisher, github = _make_publisher(update_changelog_file=True)
        github.get_file_contents.side_effect = Exception("API error")
        publisher.publish(changelog_body="body", release_tag="v1.0.0")
        github.update_release_body.assert_called_once()
