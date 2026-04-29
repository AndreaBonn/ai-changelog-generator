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

    def test_returns_tag_across_page_boundary(self) -> None:
        client = _make_client()
        page1 = [{"name": "v1.1.0"}]
        page2 = [{"name": "v1.0.0"}]
        responses = [
            _mock_response(json_data=page1),
            _mock_response(json_data=page2),
            _mock_response(json_data=[]),
        ]
        with patch.object(client._session, "request", side_effect=responses):
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


class TestReleaseOperations:
    def test_update_release_body_calls_patch(self) -> None:
        client = _make_client()
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data={"id": 42})
        ) as mock_req:
            client.update_release_body("42", "new body")
        assert mock_req.call_count == 1
        assert mock_req.call_args[0][0] == "PATCH"

    def test_get_or_create_release_updates_existing(self) -> None:
        client = _make_client()
        responses = [
            _mock_response(json_data={"id": 99}),
            _mock_response(json_data={"id": 99}),
        ]
        with patch.object(client._session, "request", side_effect=responses):
            client.get_or_create_release_by_tag("v1.0.0", "body")

    def test_get_or_create_release_creates_when_404(self) -> None:
        client = _make_client()
        resp_404 = _mock_response(status_code=404, json_data={})
        resp_404.text = "Not Found"
        resp_created = _mock_response(json_data={"id": 100})
        with patch.object(client._session, "request", side_effect=[resp_404, resp_created]):
            client.get_or_create_release_by_tag("v1.0.0", "body")


class TestFileOperations:
    def test_get_file_contents_returns_decoded(self) -> None:
        import base64

        content = base64.b64encode(b"hello world").decode()
        client = _make_client()
        with patch.object(
            client._session,
            "request",
            return_value=_mock_response(json_data={"content": content, "sha": "abc"}),
        ):
            decoded, sha = client.get_file_contents("README.md")
        assert decoded == "hello world"
        assert sha == "abc"

    def test_get_file_contents_returns_empty_on_404(self) -> None:
        client = _make_client()
        resp_404 = _mock_response(status_code=404, json_data={})
        resp_404.text = "Not Found"
        with patch.object(client._session, "request", return_value=resp_404):
            decoded, sha = client.get_file_contents("MISSING.md")
        assert decoded == ""
        assert sha == ""

    def test_update_file_contents_with_sha(self) -> None:
        client = _make_client()
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data={"content": {}})
        ) as mock_req:
            client.update_file_contents("CHANGELOG.md", "content", "sha123", "commit msg")
        assert mock_req.call_count == 1
        assert mock_req.call_args[0][0] == "PUT"

    def test_update_file_contents_without_sha(self) -> None:
        client = _make_client()
        with patch.object(
            client._session, "request", return_value=_mock_response(json_data={"content": {}})
        ):
            client.update_file_contents("CHANGELOG.md", "content", None, "commit msg")


class TestGetMergedPrsBaseNone:
    def test_uses_commits_endpoint_when_base_is_none(self) -> None:
        client = _make_client()
        commits_data = [{"sha": "aaa"}]
        pr_data = [
            {
                "number": 5,
                "title": "feat: init",
                "body": "",
                "labels": [{"name": "feat"}],
                "html_url": "",
                "user": {"login": "dev"},
                "merged_at": "2024-01-01T00:00:00Z",
            }
        ]
        responses = [
            _mock_response(json_data=commits_data),
            _mock_response(json_data=pr_data),
        ]
        with patch.object(client._session, "request", side_effect=responses) as mock_req:
            result = client.get_merged_prs(None, "v1.0.0", max_prs=30)
        assert len(result) == 1
        assert result[0].number == 5
        first_call_url = mock_req.call_args_list[0][0][1]
        assert "/commits" in first_call_url
        assert "compare" not in first_call_url


class TestMaxPrsTruncation:
    def test_stops_collecting_prs_at_max(self) -> None:
        client = _make_client()
        compare_data = {"commits": [{"sha": "aaa"}, {"sha": "bbb"}, {"sha": "ccc"}]}

        def make_pr(num: int) -> list[dict[str, object]]:
            return [
                {
                    "number": num,
                    "title": f"PR {num}",
                    "body": "",
                    "labels": [],
                    "html_url": "",
                    "user": {"login": "dev"},
                    "merged_at": "2024-01-01",
                }
            ]

        responses = [
            _mock_response(json_data=compare_data),
            _mock_response(json_data=make_pr(1)),
            _mock_response(json_data=make_pr(2)),
        ]
        with patch.object(client._session, "request", side_effect=responses):
            result = client.get_merged_prs("v1.0", "v1.1", max_prs=2)
        assert len(result) == 2


class TestErrorReraise:
    def test_get_or_create_release_reraises_non_404(self) -> None:
        client = _make_client()
        resp_500 = _mock_response(status_code=500, json_data={})
        with (
            patch.object(client._session, "request", return_value=resp_500),
            patch("changelog.github_client.time.sleep"),
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client.get_or_create_release_by_tag("v1.0.0", "body")
        assert exc_info.value.code == "GITHUB_API_ERROR"

    def test_get_file_contents_reraises_non_404(self) -> None:
        client = _make_client()
        resp_403 = _mock_response(status_code=403, json_data={})
        resp_403.text = "Forbidden"
        resp_403.headers = {}
        with (
            patch.object(client._session, "request", return_value=resp_403),
            pytest.raises(GitHubAPIError),
        ):
            client.get_file_contents("SECRET.md")


class TestConnectionRetry:
    @patch("changelog.github_client.time.sleep")
    def test_connection_error_retries_then_succeeds(self, mock_sleep: MagicMock) -> None:
        import requests as req

        client = _make_client()
        tags = [{"name": "v1.0.0"}]
        responses = [
            req.ConnectionError("down"),
            _mock_response(json_data=tags),
            _mock_response(json_data=[]),
        ]
        with patch.object(client._session, "request", side_effect=responses):
            result = client.get_previous_tag("v1.0.0")
        assert result is None
        assert mock_sleep.call_count == 1

    @patch("changelog.github_client.time.sleep")
    def test_connection_error_exhausts_retries(self, mock_sleep: MagicMock) -> None:
        import requests as req

        client = _make_client()
        with (
            patch.object(
                client._session,
                "request",
                side_effect=req.ConnectionError("always down"),
            ),
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client.get_previous_tag("v1.0.0")
        assert "retries exhausted" in exc_info.value.message


class TestTypeGuards:
    def test_get_dict_raises_when_api_returns_list(self) -> None:
        client = _make_client()
        with (
            patch.object(
                client._session, "request", return_value=_mock_response(json_data=[{"a": 1}])
            ),
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client._get_dict("/repos/owner/repo/releases/tags/v1")
        assert "Expected dict" in exc_info.value.message

    def test_get_list_raises_when_api_returns_dict(self) -> None:
        client = _make_client()
        with (
            patch.object(
                client._session, "request", return_value=_mock_response(json_data={"a": 1})
            ),
            pytest.raises(GitHubAPIError) as exc_info,
        ):
            client._get_list("/repos/owner/repo/tags")
        assert "Expected list" in exc_info.value.message
