"""Tests for changelog.evaluator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from changelog.classifier import ClassifiedChanges
from changelog.evaluator import Evaluator
from changelog.providers import get_provider


def _chain() -> list[tuple[MagicMock, str]]:
    p = get_provider(name="groq", api_key="key1")
    return [(p, "system")]  # type: ignore[list-item]


def _classified() -> ClassifiedChanges:
    return ClassifiedChanges(
        breaking=["API v1 removed"],
        features=["dark mode"],
        fixes=["null pointer"],
    )


class TestEvaluator:
    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_returns_original_when_ok(self, mock_llm: MagicMock) -> None:
        mock_llm.return_value = '{"ok": true, "feedback": "", "missing": []}'
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "original"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_regenerates_when_not_ok(self, mock_llm: MagicMock) -> None:
        mock_llm.side_effect = [
            '{"ok": false, "feedback": "missing breaking change", "missing": ["API v1"]}',
            "regenerated changelog",
            '{"ok": true, "feedback": "", "missing": []}',
        ]
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "regenerated changelog"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_stops_after_max_retries(self, mock_llm: MagicMock) -> None:
        mock_llm.return_value = '{"ok": false, "feedback": "still bad", "missing": []}'
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=0,
        )
        assert result == "original"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_returns_last_body_on_exhausted_retries(self, mock_llm: MagicMock) -> None:
        mock_llm.side_effect = [
            '{"ok": false, "feedback": "missing X", "missing": ["X"]}',
            "second attempt body",
            '{"ok": false, "feedback": "still missing", "missing": ["X"]}',
        ]
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "second attempt body"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_invalid_json_treated_as_ok(self, mock_llm: MagicMock) -> None:
        mock_llm.return_value = "this is not json at all"
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "original"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_llm_exception_returns_current_body(self, mock_llm: MagicMock) -> None:
        mock_llm.side_effect = Exception("LLM down")
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "original"

    @patch("changelog.evaluator.call_llm_with_fallback")
    def test_feedback_passed_to_regeneration(self, mock_llm: MagicMock) -> None:
        mock_llm.side_effect = [
            '{"ok": false, "feedback": "missing breaking change", "missing": ["API v1"]}',
            "regenerated with feedback",
            '{"ok": true, "feedback": "", "missing": []}',
        ]
        evaluator = Evaluator(provider_chain=_chain())
        result = evaluator.evaluate_and_refine(
            changelog_body="original",
            classified=_classified(),
            language="english",
            max_retries=1,
        )
        assert result == "regenerated with feedback"
        regen_call = mock_llm.call_args_list[1]
        regen_prompt = regen_call[1]["user"] if "user" in regen_call[1] else regen_call[0][1]
        assert "missing breaking change" in regen_prompt
