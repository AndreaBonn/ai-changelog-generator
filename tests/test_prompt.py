"""Tests for changelog.prompt."""

from __future__ import annotations

from changelog.classifier import ClassifiedChanges
from changelog.prompt import build_evaluation_prompt, build_generation_prompt, get_system_prompt


def _classified(**kwargs: list[str]) -> ClassifiedChanges:
    defaults: dict[str, list[str]] = {
        "breaking": [],
        "features": [],
        "fixes": [],
        "performance": [],
        "docs": [],
        "refactor": [],
        "chore": [],
        "other": [],
    }
    defaults.update(kwargs)
    return ClassifiedChanges(**defaults)


class TestSystemPrompt:
    def test_returns_non_empty_string(self) -> None:
        prompt = get_system_prompt()
        assert len(prompt) > 50
        assert "technical writer" in prompt.lower()


class TestGenerationPrompt:
    def test_includes_release_tag(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(),
            release_tag="v2.0.0",
            release_name="v2.0.0",
            previous_tag="v1.0.0",
            language="english",
            repo="owner/repo",
        )
        assert "v2.0.0" in prompt

    def test_includes_previous_tag_context(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(),
            release_tag="v2.0.0",
            release_name="v2.0.0",
            previous_tag="v1.0.0",
            language="english",
            repo="owner/repo",
        )
        assert "v1.0.0" in prompt
        assert "since" in prompt.lower()

    def test_first_release_context(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(),
            release_tag="v1.0.0",
            release_name="v1.0.0",
            previous_tag=None,
            language="english",
            repo="owner/repo",
        )
        assert "first release" in prompt.lower()

    def test_includes_non_empty_categories(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(features=["login system (#1)"], fixes=["null check (#2)"]),
            release_tag="v1.0.0",
            release_name="v1.0.0",
            previous_tag=None,
            language="english",
            repo="owner/repo",
        )
        assert "login system (#1)" in prompt
        assert "null check (#2)" in prompt

    def test_omits_empty_categories_content(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(features=["new thing"]),
            release_tag="v1.0.0",
            release_name="v1.0.0",
            previous_tag=None,
            language="english",
            repo="owner/repo",
        )
        assert "new thing" in prompt

    def test_includes_feedback_when_provided(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(),
            release_tag="v1.0.0",
            release_name="v1.0.0",
            previous_tag=None,
            language="english",
            repo="owner/repo",
            feedback="Missing breaking change about API removal",
            missing=["API v1 removal"],
        )
        assert "Missing breaking change" in prompt
        assert "API v1 removal" in prompt

    def test_includes_language_instruction(self) -> None:
        prompt = build_generation_prompt(
            classified=_classified(),
            release_tag="v1.0.0",
            release_name="v1.0.0",
            previous_tag=None,
            language="italian",
            repo="owner/repo",
        )
        assert "italian" in prompt.lower()


class TestEvaluationPrompt:
    def test_includes_changelog_body(self) -> None:
        prompt = build_evaluation_prompt(
            changelog_body="## What's Changed\n- Added login",
            classified=_classified(features=["login"]),
            language="english",
        )
        assert "Added login" in prompt

    def test_includes_all_classified_items(self) -> None:
        prompt = build_evaluation_prompt(
            changelog_body="some changelog",
            classified=_classified(
                breaking=["removed v1 API"],
                features=["new dashboard"],
                fixes=["null pointer fix"],
            ),
            language="english",
        )
        assert "removed v1 API" in prompt
        assert "new dashboard" in prompt
        assert "null pointer fix" in prompt

    def test_requests_json_response(self) -> None:
        prompt = build_evaluation_prompt(
            changelog_body="changelog",
            classified=_classified(),
            language="english",
        )
        assert '"ok"' in prompt
        assert "JSON" in prompt
