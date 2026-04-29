"""Configuration loader — single source of truth for environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from changelog.exceptions import ConfigError

log = logging.getLogger("ai-changelog-generator")

SUPPORTED_LANGUAGES = frozenset({"english", "italian", "french", "spanish", "german"})


@dataclass
class Config:
    """Immutable configuration loaded from environment variables."""

    repo: str
    github_token: str
    release_tag: str
    release_name: str
    release_id: str
    default_branch: str
    llm_providers: list[str]
    llm_api_keys: list[str]
    llm_model: str
    language: str
    update_changelog_file: bool
    changelog_file_path: str
    max_commits: int
    max_prs: int
    max_eval_retries: int

    @classmethod
    def from_env(cls) -> Config:
        """Build Config from environment variables injected by action.yml."""
        repo = os.environ.get("REPO_FULL_NAME", "")
        github_token = os.environ.get("GITHUB_TOKEN", "")
        release_tag = os.environ.get("RELEASE_TAG", "")
        release_name = os.environ.get("RELEASE_NAME", release_tag)
        release_id = os.environ.get("RELEASE_ID", "")
        default_branch = os.environ.get("DEFAULT_BRANCH", "main")

        if not release_tag:
            raise ConfigError("CONFIG_INVALID", "RELEASE_TAG is required")
        if not github_token:
            raise ConfigError("CONFIG_INVALID", "GITHUB_TOKEN is required")
        if not repo:
            raise ConfigError("CONFIG_INVALID", "REPO_FULL_NAME is required")

        raw_providers = os.environ.get("LLM_PROVIDER", "groq")
        raw_keys = os.environ.get("LLM_API_KEY", "")
        if not raw_keys:
            raise ConfigError("CONFIG_INVALID", "LLM_API_KEY is required")

        providers = [p.strip() for p in raw_providers.split(",") if p.strip()]
        api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

        if len(providers) != len(api_keys):
            raise ConfigError(
                "CONFIG_INVALID",
                f"LLM_PROVIDER count ({len(providers)}) does not match "
                f"LLM_API_KEY count ({len(api_keys)})",
            )

        llm_model = os.environ.get("LLM_MODEL", "")

        language = os.environ.get("CHANGELOG_LANGUAGE", "english").lower()
        if language not in SUPPORTED_LANGUAGES:
            log.warning("Unknown language '%s', falling back to 'english'.", language)
            language = "english"

        update_changelog_file = os.environ.get("UPDATE_CHANGELOG_FILE", "false").lower() == "true"
        changelog_file_path = os.environ.get("CHANGELOG_FILE_PATH", "CHANGELOG.md")

        max_commits = _parse_positive_int("MAX_COMMITS", default=100)
        max_prs = _parse_positive_int("MAX_PRS", default=30)
        max_eval_retries = _parse_non_negative_int("MAX_EVAL_RETRIES", default=1)

        return cls(
            repo=repo,
            github_token=github_token,
            release_tag=release_tag,
            release_name=release_name,
            release_id=release_id,
            default_branch=default_branch,
            llm_providers=providers,
            llm_api_keys=api_keys,
            llm_model=llm_model,
            language=language,
            update_changelog_file=update_changelog_file,
            changelog_file_path=changelog_file_path,
            max_commits=max_commits,
            max_prs=max_prs,
            max_eval_retries=max_eval_retries,
        )


def _parse_positive_int(env_var: str, *, default: int) -> int:
    raw = os.environ.get(env_var, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as err:
        raise ConfigError(
            "CONFIG_INVALID", f"{env_var} must be a positive integer, got '{raw}'"
        ) from err
    if value <= 0:
        raise ConfigError("CONFIG_INVALID", f"{env_var} must be positive, got {value}")
    return value


def _parse_non_negative_int(env_var: str, *, default: int) -> int:
    raw = os.environ.get(env_var, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as err:
        raise ConfigError(
            "CONFIG_INVALID", f"{env_var} must be a non-negative integer, got '{raw}'"
        ) from err
    if value < 0:
        raise ConfigError("CONFIG_INVALID", f"{env_var} must be non-negative, got {value}")
    return value
