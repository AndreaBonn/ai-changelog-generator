"""Tests for changelog.github_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from changelog.exceptions import GitHubAPIError
from changelog.github_client import GitHubClient


def _make_client() -> GitHubClient:
    return GitHubClient(token="test-token", repo="owner/repo")


def _mock_response(
    status_code: int = 200,
    json_data: object = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    resp.headers = headers or {}
    return resp


class TestGetPreviousTag:
    def test_returns_second_tag_in_list(self) -> None:
        client = _make_client()
        tags = [{"name": "v1.1.0"}, {"name": "v1.0.0"}, {"name": "v0.9.0"}]
        with patch.object(client._session, "request", return_value=_mock_response(json_data=tags)):
            result = client.get_previous_tag("v1.1.0")
        assert result == "v1.0.0"

    def test_returns_none_for_first_release(self) -> None:
        client = _make_client()
        tags = [{"name": "v1.0.0"}]
        responses = [_mock_response(json_data=tags), _mock_response(json_data=[])]
        with patch.object(client._session, "request", side_effect=responses):
            result = client.get_previous_tag("v1.0.0")
        assert result is None


class TestGetCommitsBetween:
    def test_uses_compare_endpoint_with_base(self) -> None:
        client = _make_client()
        compare_data = {
            "commits": [
                {
                    "sha": "abc1234",
                    "commit": {"message": "feat: add login"},
                    "author": {"login": "dev1"},
                    "html_url": "https://github.com/owner/repo/commit/abc1234",
                }
            ]
        }
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data=compare_data)
        ) as mock_req:
            result = client.get_commits_between("v1.0.0", "v1.1.0", max_commits=100)
        assert len(result) == 1
        assert result[0].sha == "abc1234"
        assert result[0].message == "feat: add login"
        call_url = mock_req.call_args[0][1]
        assert "compare/v1.0.0...v1.1.0" in call_url

    def test_uses_commits_endpoint_when_base_is_none(self) -> None:
        client = _make_client()
        commits_data = [
            {
                "sha": "def5678",
                "commit": {"message": "initial commit"},
                "author": {"login": "dev1"},
                "html_url": "https://github.com/owner/repo/commit/def5678",
            }
        ]
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data=commits_data)
        ) as mock_req:
            result = client.get_commits_between(None, "v1.0.0", max_commits=100)
        assert len(result) == 1
        call_url = mock_req.call_args[0][1]
        assert "/commits" in call_url
        assert "compare" not in call_url

    def test_truncates_to_max_commits(self) -> None:
        client = _make_client()
        commits = [
            {
                "sha": f"sha{i}",
                "commit": {"message": f"commit {i}"},
                "author": {"login": "dev"},
                "html_url": f"https://github.com/owner/repo/commit/sha{i}",
            }
            for i in range(10)
        ]
        compare_data = {"commits": commits}
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data=compare_data)
        ):
            result = client.get_commits_between("v0.9", "v1.0", max_commits=3)
        assert len(result) == 3


class TestGetMergedPrs:
    def test_deduplicates_by_pr_number(self) -> None:
        client = _make_client()
        compare_data = {
            "commits": [
                {"sha": "aaa"},
                {"sha": "bbb"},
            ]
        }
        pr_data = [
            {
                "number": 42,
                "title": "feat: login",
                "body": "",
                "labels": [],
                "html_url": "https://github.com/owner/repo/pull/42",
                "user": {"login": "dev"},
                "merged_at": "2024-01-01T00:00:00Z",
            }
        ]
        responses = [
            _mock_response(json_data=compare_data),
            _mock_response(json_data=pr_data),
            _mock_response(json_data=pr_data),
        ]
        with patch.object(client._session, "request", side_effect=responses):
            result = client.get_merged_prs("v1.0", "v1.1", max_prs=30)
        assert len(result) == 1
        assert result[0].number == 42

    def test_skips_non_merged_prs(self) -> None:
        client = _make_client()
        compare_data = {"commits": [{"sha": "aaa"}]}
        pr_data = [
            {
                "number": 10,
                "title": "wip",
                "body": "",
                "labels": [],
                "html_url": "",
                "user": {"login": "dev"},
                "merged_at": None,
            }
        ]
        responses = [
            _mock_response(json_data=compare_data),
            _mock_response(json_data=pr_data),
        ]
        with patch.object(client._session, "request", side_effect=responses):
            result = client.get_merged_prs("v1.0", "v1.1", max_prs=30)
        assert len(result) == 0


class TestHttpBehaviour:
    def test_4xx_raises_immediately_no_retry(self) -> None:
        client = _make_client()
        resp = _mock_response(status_code=422, json_data={})
        resp.text = "Validation failed"
        with (
            patch.object(client._session, "request", return_value=resp) as mock_req,
            pytest.raises(GitHubAPIError),
        ):
            client.get_previous_tag("v1.0.0")
        assert mock_req.call_count == 1

    @patch("changelog.github_client.time.sleep")
    def test_5xx_retries_up_to_max(self, mock_sleep: MagicMock) -> None:
        client = _make_client()
        resp_500 = _mock_response(status_code=500, json_data={})
        with (
            patch.object(client._session, "request", return_value=resp_500) as mock_req,
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client.get_previous_tag("v1.0.0")
        assert mock_req.call_count == 3
        assert "retries exhausted" in exc_info.value.message

    def test_rate_limit_raises_with_correct_code(self) -> None:
        client = _make_client()
        resp = _mock_response(
            status_code=403,
            json_data={},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        )
        with (
            patch.object(client._session, "request", return_value=resp),
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client.get_previous_tag("v1.0.0")
        assert exc_info.value.code == "RATE_LIMITED"
