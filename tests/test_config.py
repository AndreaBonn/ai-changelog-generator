"""Tests for changelog.config."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from changelog.config import Config
from changelog.exceptions import ConfigError

MINIMAL_ENV = {
    "REPO_FULL_NAME": "owner/repo",
    "GITHUB_TOKEN": "ghp_test123",
    "RELEASE_TAG": "v1.0.0",
    "LLM_API_KEY": "key1",
}


class TestConfigFromEnv:
    def test_minimal_valid_config(self) -> None:
        with patch.dict(os.environ, MINIMAL_ENV, clear=True):
            cfg = Config.from_env()
        assert cfg.repo == "owner/repo"
        assert cfg.release_tag == "v1.0.0"
        assert cfg.llm_providers == ["groq"]
        assert cfg.language == "english"
        assert cfg.max_commits == 100
        assert cfg.max_eval_retries == 1

    def test_missing_release_tag_raises(self) -> None:
        env = {**MINIMAL_ENV}
        del env["RELEASE_TAG"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError) as exc_info:
            Config.from_env()
        assert exc_info.value.code == "CONFIG_INVALID"

    def test_missing_github_token_raises(self) -> None:
        env = {**MINIMAL_ENV}
        del env["GITHUB_TOKEN"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError):
            Config.from_env()

    def test_missing_api_key_raises(self) -> None:
        env = {**MINIMAL_ENV}
        del env["LLM_API_KEY"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError):
            Config.from_env()

    def test_provider_key_count_mismatch_raises(self) -> None:
        env = {**MINIMAL_ENV, "LLM_PROVIDER": "groq,gemini", "LLM_API_KEY": "key1"}
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError) as exc_info:
            Config.from_env()
        assert "count" in exc_info.value.message.lower()

    def test_unknown_language_falls_back_to_english(self) -> None:
        env = {**MINIMAL_ENV, "CHANGELOG_LANGUAGE": "klingon"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.language == "english"

    def test_boolean_parsing_true(self) -> None:
        env = {**MINIMAL_ENV, "UPDATE_CHANGELOG_FILE": "true"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.update_changelog_file is True

    def test_boolean_parsing_false(self) -> None:
        env = {**MINIMAL_ENV, "UPDATE_CHANGELOG_FILE": "false"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.update_changelog_file is False

    def test_multi_provider_parsing(self) -> None:
        env = {**MINIMAL_ENV, "LLM_PROVIDER": "groq,gemini", "LLM_API_KEY": "key1,key2"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.llm_providers == ["groq", "gemini"]
        assert cfg.llm_api_keys == ["key1", "key2"]

    def test_invalid_max_commits_raises(self) -> None:
        env = {**MINIMAL_ENV, "MAX_COMMITS": "abc"}
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError):
            Config.from_env()

    def test_negative_max_commits_raises(self) -> None:
        env = {**MINIMAL_ENV, "MAX_COMMITS": "-5"}
        with patch.dict(os.environ, env, clear=True), pytest.raises(ConfigError):
            Config.from_env()

    def test_zero_max_eval_retries_allowed(self) -> None:
        env = {**MINIMAL_ENV, "MAX_EVAL_RETRIES": "0"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.max_eval_retries == 0
