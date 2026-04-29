"""Domain exceptions for the changelog generator."""

from __future__ import annotations


class ChangelogError(Exception):
    """Base exception for all domain errors."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class ConfigError(ChangelogError):
    """Invalid or missing configuration."""


class GitHubAPIError(ChangelogError):
    """GitHub API returned a non-2xx response."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(code, message)
        self.status_code = status_code


class LLMError(ChangelogError):
    """LLM provider call failed."""


class PublishError(ChangelogError):
    """Failed to publish the changelog."""
