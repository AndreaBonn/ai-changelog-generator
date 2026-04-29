"""Tests for changelog.providers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from changelog.exceptions import LLMError
from changelog.providers import (
    Provider,
    call_llm_with_fallback,
    get_provider,
)


def _mock_response(status_code: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    return resp


def _make_chain(providers: list[Provider]) -> list[tuple[Provider, str]]:
    return [(p, "system prompt") for p in providers]


class TestGetProvider:
    def test_groq_request_body_structure(self) -> None:
        p = get_provider(name="groq", api_key="key1")
        body = p.request_builder("sys", "user", p.model, 0.3)
        assert body["model"] == "meta-llama/llama-4-scout-17b-16e-instruct"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"
        assert body["temperature"] == 0.3

    def test_gemini_request_body_structure(self) -> None:
        p = get_provider(name="gemini", api_key="key1")
        body = p.request_builder("sys", "user", p.model, 0.3)
        assert "system_instruction" in body
        assert body["contents"][0]["role"] == "user"

    def test_gemini_api_key_in_header_not_url(self) -> None:
        p = get_provider(name="gemini", api_key="secret-key")
        assert "secret-key" not in p.endpoint
        assert p.headers["x-goog-api-key"] == "secret-key"

    def test_anthropic_request_body_structure(self) -> None:
        p = get_provider(name="anthropic", api_key="key1")
        body = p.request_builder("sys", "user", p.model, 0.3)
        assert body["model"] == "claude-sonnet-4-6"
        assert body["system"] == "sys"
        assert body["messages"][0]["role"] == "user"

    def test_openai_request_body_structure(self) -> None:
        p = get_provider(name="openai", api_key="key1")
        body = p.request_builder("sys", "user", p.model, 0.3)
        assert body["model"] == "gpt-4.1-mini"
        assert body["messages"][0]["role"] == "system"

    def test_model_override_applies(self) -> None:
        p = get_provider(name="groq", api_key="key1", model="custom-model")
        assert p.model == "custom-model"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(LLMError):
            get_provider(name="unknown", api_key="key1")


class TestCallLlmWithFallback:
    @patch("changelog.providers.requests.post")
    def test_returns_text_on_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            json_data={"choices": [{"message": {"content": "changelog text"}}]}
        )
        p = get_provider(name="groq", api_key="key1")
        result = call_llm_with_fallback(_make_chain([p]), user="generate")
        assert result == "changelog text"

    @patch("changelog.providers.requests.post")
    def test_fallback_on_500(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="groq", api_key="key1")
        p2 = get_provider(name="openai", api_key="key2")
        mock_post.side_effect = [
            _mock_response(status_code=500),
            _mock_response(status_code=500),
            _mock_response(json_data={"choices": [{"message": {"content": "fallback ok"}}]}),
        ]
        with patch("changelog.providers.time.sleep"):
            result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert result == "fallback ok"

    @patch("changelog.providers.requests.post")
    def test_fallback_on_connection_error(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="groq", api_key="key1")
        p2 = get_provider(name="openai", api_key="key2")
        mock_post.side_effect = [
            requests.ConnectionError("down"),
            requests.ConnectionError("still down"),
            _mock_response(json_data={"choices": [{"message": {"content": "recovered"}}]}),
        ]
        with patch("changelog.providers.time.sleep"):
            result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert result == "recovered"

    @patch("changelog.providers.requests.post")
    def test_no_retry_on_4xx(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="groq", api_key="key1")
        p2 = get_provider(name="openai", api_key="key2")
        mock_post.side_effect = [
            _mock_response(status_code=401),
            _mock_response(json_data={"choices": [{"message": {"content": "ok"}}]}),
        ]
        result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert result == "ok"
        assert mock_post.call_count == 2

    @patch("changelog.providers.requests.post")
    def test_raises_when_all_fail(self, mock_post: MagicMock) -> None:
        p = get_provider(name="groq", api_key="key1")
        mock_post.return_value = _mock_response(status_code=401)
        with pytest.raises(LLMError) as exc_info:
            call_llm_with_fallback(_make_chain([p]), user="generate")
        assert exc_info.value.code == "ALL_PROVIDERS_FAILED"

    @patch("changelog.providers.requests.post")
    def test_empty_response_triggers_fallback(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="groq", api_key="key1")
        p2 = get_provider(name="openai", api_key="key2")
        mock_post.side_effect = [
            _mock_response(json_data={"choices": [{"message": {"content": ""}}]}),
            _mock_response(json_data={"choices": [{"message": {"content": "real content"}}]}),
        ]
        result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert result == "real content"

    @patch("changelog.providers.requests.post")
    def test_rate_limit_429_triggers_fallback(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="gemini", api_key="key1")
        p2 = get_provider(name="groq", api_key="key2")
        mock_post.side_effect = [
            _mock_response(status_code=429),
            _mock_response(json_data={"choices": [{"message": {"content": "from groq"}}]}),
        ]
        result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert result == "from groq"

    @patch("changelog.providers.requests.post")
    def test_rate_limit_429_no_retry_within_provider(self, mock_post: MagicMock) -> None:
        p1 = get_provider(name="gemini", api_key="key1")
        p2 = get_provider(name="groq", api_key="key2")
        mock_post.side_effect = [
            _mock_response(status_code=429),
            _mock_response(json_data={"choices": [{"message": {"content": "ok"}}]}),
        ]
        result = call_llm_with_fallback(_make_chain([p1, p2]), user="generate")
        assert mock_post.call_count == 2
        assert result == "ok"


class TestResponseExtractors:
    def test_groq_extracts_content(self) -> None:
        p = get_provider(name="groq", api_key="key1")
        text = p.response_extractor({"choices": [{"message": {"content": "hello"}}]})
        assert text == "hello"

    def test_gemini_extracts_content(self) -> None:
        p = get_provider(name="gemini", api_key="key1")
        text = p.response_extractor(
            {"candidates": [{"content": {"parts": [{"text": "gemini says"}]}}]}
        )
        assert text == "gemini says"

    def test_anthropic_extracts_content(self) -> None:
        p = get_provider(name="anthropic", api_key="key1")
        text = p.response_extractor({"content": [{"text": "claude says"}]})
        assert text == "claude says"
