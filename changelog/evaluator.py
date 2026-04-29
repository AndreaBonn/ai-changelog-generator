"""Self-evaluation loop for generated changelogs. Never blocks publishing."""

from __future__ import annotations

import json
import logging
from typing import Any

from changelog.classifier import ClassifiedChanges
from changelog.prompt import build_evaluation_prompt, build_generation_prompt
from changelog.providers import (
    EVALUATION_TEMPERATURE,
    Provider,
    call_llm_with_fallback,
)

log = logging.getLogger("ai-changelog-generator")


class Evaluator:
    """Evaluate and optionally refine a generated changelog via LLM self-review."""

    def __init__(self, *, provider_chain: list[tuple[Provider, str]]) -> None:
        self._provider_chain = provider_chain

    def evaluate_and_refine(
        self,
        *,
        changelog_body: str,
        classified: ClassifiedChanges,
        language: str,
        max_retries: int,
        release_tag: str = "",
        release_name: str = "",
        previous_tag: str | None = None,
        repo: str = "",
    ) -> str:
        """Run self-evaluation loop. Returns the best changelog body available."""
        for attempt in range(max_retries + 1):
            eval_prompt = build_evaluation_prompt(
                changelog_body=changelog_body,
                classified=classified,
                language=language,
            )

            try:
                raw_response = call_llm_with_fallback(
                    self._provider_chain,
                    user=eval_prompt,
                    temperature=EVALUATION_TEMPERATURE,
                )
                evaluation = _parse_evaluation(raw_response)
            except Exception:
                log.warning(
                    "Evaluator failed (attempt %d), keeping current body.",
                    attempt + 1,
                    exc_info=True,
                )
                return changelog_body

            if evaluation["ok"]:
                log.info("Evaluation passed (attempt %d).", attempt + 1)
                return changelog_body

            if attempt >= max_retries:
                log.warning(
                    "Evaluation failed after %d retries, publishing last body. Feedback: %s",
                    max_retries,
                    evaluation["feedback"],
                )
                return changelog_body

            log.info(
                "Evaluation failed (attempt %d): %s. Regenerating.",
                attempt + 1,
                evaluation["feedback"],
            )

            regen_prompt = build_generation_prompt(
                classified=classified,
                release_tag=release_tag,
                release_name=release_name,
                previous_tag=previous_tag,
                language=language,
                repo=repo,
                feedback=evaluation["feedback"],
                missing=evaluation["missing"],
            )

            try:
                changelog_body = call_llm_with_fallback(self._provider_chain, user=regen_prompt)
            except Exception:
                log.warning("Regeneration failed, keeping previous body.", exc_info=True)
                return changelog_body

        return changelog_body


def _parse_evaluation(raw: str) -> dict[str, Any]:
    """Parse LLM evaluation response as JSON. Returns ok=True on parse failure (fail-safe)."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:])
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Failed to parse evaluation JSON, treating as ok. Raw: %s", raw[:200])
        return {"ok": True, "feedback": "", "missing": []}

    return {
        "ok": bool(data.get("ok", True)),
        "feedback": str(data.get("feedback", "")),
        "missing": list(data.get("missing", [])),
    }
