"""Tests for generate.py — integration tests with all dependencies mocked."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from changelog.exceptions import ChangelogError

FULL_ENV = {
    "REPO_FULL_NAME": "owner/repo",
    "GITHUB_TOKEN": "ghp_test",
    "RELEASE_TAG": "v1.0.0",
    "RELEASE_NAME": "v1.0.0",
    "RELEASE_ID": "42",
    "DEFAULT_BRANCH": "main",
    "LLM_PROVIDER": "groq",
    "LLM_API_KEY": "key1",
    "LLM_MODEL": "",
    "CHANGELOG_LANGUAGE": "english",
    "UPDATE_CHANGELOG_FILE": "false",
    "CHANGELOG_FILE_PATH": "CHANGELOG.md",
    "MAX_COMMITS": "100",
    "MAX_PRS": "30",
    "MAX_EVAL_RETRIES": "1",
}


class TestMainHappyPath:
    @patch("changelog.providers.requests.post")
    @patch("changelog.github_client.GitHubClient._request")
    def test_full_pipeline_generates_and_publishes(
        self,
        mock_gh_request: MagicMock,
        mock_llm_post: MagicMock,
    ) -> None:
        mock_gh_request.side_effect = [
            [{"name": "v1.0.0"}, {"name": "v0.9.0"}],
            {
                "commits": [
                    {
                        "sha": "abc1234",
                        "commit": {"message": "feat: add login"},
                        "author": {"login": "dev"},
                        "html_url": "",
                    }
                ]
            },
            {"commits": [{"sha": "abc1234"}]},
            [
                {
                    "number": 1,
                    "title": "feat: login",
                    "body": "",
                    "labels": [],
                    "html_url": "",
                    "user": {"login": "dev"},
                    "merged_at": "2024-01-01",
                }
            ],
            {"id": 42},
        ]

        llm_resp = MagicMock()
        llm_resp.status_code = 200
        llm_resp.json.return_value = {
            "choices": [{"message": {"content": "## Changelog\n- login feature"}}]
        }
        eval_resp = MagicMock()
        eval_resp.status_code = 200
        eval_resp.json.return_value = {
            "choices": [{"message": {"content": '{"ok": true, "feedback": "", "missing": []}'}}]
        }
        mock_llm_post.side_effect = [llm_resp, eval_resp]

        with patch.dict(os.environ, FULL_ENV, clear=True):
            from generate import main

            main()

        assert mock_gh_request.call_count == 5


class TestEarlyExit:
    @patch("changelog.github_client.GitHubClient._request")
    def test_exits_early_when_no_commits_no_prs(
        self,
        mock_gh_request: MagicMock,
    ) -> None:
        mock_gh_request.side_effect = [
            [{"name": "v1.0.0"}, {"name": "v0.9.0"}],
            {"commits": []},
            {"commits": []},
        ]

        with patch.dict(os.environ, FULL_ENV, clear=True):
            from generate import main

            main()

        assert mock_gh_request.call_count == 3


class TestEvalSkip:
    @patch("changelog.providers.requests.post")
    @patch("changelog.github_client.GitHubClient._request")
    def test_skips_evaluation_when_retries_zero(
        self,
        mock_gh_request: MagicMock,
        mock_llm_post: MagicMock,
    ) -> None:
        mock_gh_request.side_effect = [
            [{"name": "v1.0.0"}, {"name": "v0.9.0"}],
            {
                "commits": [
                    {
                        "sha": "abc1234",
                        "commit": {"message": "fix: bug"},
                        "author": {"login": "dev"},
                        "html_url": "",
                    }
                ]
            },
            {"commits": [{"sha": "abc1234"}]},
            [],
            {"id": 42},
        ]

        llm_resp = MagicMock()
        llm_resp.status_code = 200
        llm_resp.json.return_value = {
            "choices": [{"message": {"content": "## Changelog\n- bug fix"}}]
        }
        mock_llm_post.return_value = llm_resp

        env = {**FULL_ENV, "MAX_EVAL_RETRIES": "0"}
        with patch.dict(os.environ, env, clear=True):
            from generate import main

            main()

        assert mock_llm_post.call_count == 1


class TestExitCodes:
    def test_exit_code_1_on_changelog_error(self) -> None:
        with (
            patch.dict(os.environ, FULL_ENV, clear=True),
            patch("generate.main", side_effect=ChangelogError("TEST", "test error")),
            pytest.raises(SystemExit) as exc_info,
        ):
            from generate import entrypoint

            entrypoint()
        assert exc_info.value.code == 1

    def test_exit_code_2_on_unexpected_error(self) -> None:
        with (
            patch.dict(os.environ, FULL_ENV, clear=True),
            patch("generate.main", side_effect=RuntimeError("unexpected")),
            pytest.raises(SystemExit) as exc_info,
        ):
            from generate import entrypoint

            entrypoint()
        assert exc_info.value.code == 2
