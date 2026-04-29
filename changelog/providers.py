"""Multi-provider LLM client with fallback chain and key rotation."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from changelog.exceptions import LLMError

log = logging.getLogger("ai-changelog-generator")

LLM_TIMEOUT = 60
LLM_MAX_RETRIES = 3
LLM_BACKOFF_BASE = 2

_NON_RETRYABLE_STATUS_CODES = frozenset({401, 403, 413})

GENERATION_TEMPERATURE = 0.3
EVALUATION_TEMPERATURE = 0.1

DEFAULT_MODELS: dict[str, str] = {
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1-mini",
}


@dataclass
class Provider:
    """LLM provider configuration and request/response adapters."""

    name: str
    api_key: str
    model: str
    endpoint: str
    headers: dict[str, str]
    max_tokens: int
    request_builder: Callable[[str, str, str, float, int], dict[str, Any]]
    response_extractor: Callable[[dict[str, Any]], str]
    truncation_checker: Callable[[dict[str, Any]], bool]


def get_provider(*, name: str, api_key: str, model: str = "", max_tokens: int = 4096) -> Provider:
    """Build a Provider for the given name, applying model override if non-empty."""
    name_lower = name.lower().strip()
    resolved_model = model or DEFAULT_MODELS.get(name_lower, "")

    if name_lower == "groq":
        return _build_groq(api_key, resolved_model, max_tokens)
    if name_lower == "gemini":
        return _build_gemini(api_key, resolved_model, max_tokens)
    if name_lower == "anthropic":
        return _build_anthropic(api_key, resolved_model, max_tokens)
    if name_lower == "openai":
        return _build_openai(api_key, resolved_model, max_tokens)

    raise LLMError("ALL_PROVIDERS_FAILED", f"Unknown provider: {name}")


def call_llm_with_fallback(
    provider_chain: list[tuple[Provider, str]],
    *,
    user: str,
    temperature: float = GENERATION_TEMPERATURE,
) -> str:
    """Try each provider in order, falling back on failure or rate limiting."""
    errors: list[str] = []

    for provider, system_prompt in provider_chain:
        try:
            result = _call_single_provider(
                provider, system_prompt=system_prompt, user_prompt=user, temperature=temperature
            )
            if result.strip():
                return result
            log.warning("Empty response from %s/%s, trying next.", provider.name, provider.model)
            errors.append(f"{provider.name}: empty response")
        except _RateLimitError as exc:
            log.warning(
                "Rate limited on %s/%s: %s. Trying next.", provider.name, provider.model, exc
            )
            errors.append(f"{provider.name}: rate limited")
        except (requests.RequestException, LLMError) as exc:
            log.warning("Provider %s/%s failed: %s", provider.name, provider.model, exc)
            errors.append(f"{provider.name}: {exc}")

    raise LLMError("ALL_PROVIDERS_FAILED", f"All providers failed: {'; '.join(errors)}")


class _RateLimitError(Exception):
    """Internal signal for rate limit responses — triggers fallback to next provider."""


_session = requests.Session()


def _call_single_provider(
    provider: Provider,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> str:
    """Call a single provider with per-provider retry on 5xx."""
    body = provider.request_builder(
        system_prompt, user_prompt, provider.model, temperature, provider.max_tokens
    )

    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = _session.post(
                provider.endpoint,
                headers=provider.headers,
                json=body,
                timeout=LLM_TIMEOUT,
            )
        except requests.RequestException:
            if attempt < LLM_MAX_RETRIES - 1:
                time.sleep(LLM_BACKOFF_BASE * (2**attempt))
                continue
            raise

        if resp.status_code == 429:
            raise _RateLimitError(f"HTTP 429 from {provider.name}")

        if resp.status_code in _NON_RETRYABLE_STATUS_CODES:
            raise LLMError(
                "ALL_PROVIDERS_FAILED",
                f"{provider.name} returned {resp.status_code}: {resp.text[:200]}",
            )

        if resp.status_code >= 500:
            if attempt < LLM_MAX_RETRIES - 1:
                log.warning(
                    "LLM %s returned %d (attempt %d), retrying.",
                    provider.name,
                    resp.status_code,
                    attempt + 1,
                )
                time.sleep(LLM_BACKOFF_BASE * (2**attempt))
                continue
            raise LLMError(
                "ALL_PROVIDERS_FAILED",
                f"{provider.name} returned {resp.status_code} after {LLM_MAX_RETRIES} retries",
            )

        if resp.status_code >= 400:
            raise LLMError(
                "ALL_PROVIDERS_FAILED",
                f"{provider.name} returned {resp.status_code}: {resp.text[:200]}",
            )

        data: dict[str, Any] = resp.json()
        if provider.truncation_checker(data):
            log.warning(
                "LLM %s/%s output was truncated (hit max_tokens=%d). "
                "Consider increasing MAX_TOKENS.",
                provider.name,
                provider.model,
                provider.max_tokens,
            )
        return provider.response_extractor(data)

    # Unreachable: every loop iteration terminates via return, raise, or continue
    # with the last attempt always raising directly.
    raise LLMError(
        "ALL_PROVIDERS_FAILED", f"{provider.name}: max retries exhausted"
    )  # pragma: no cover


def _build_groq(api_key: str, model: str, max_tokens: int) -> Provider:
    return Provider(
        name="groq",
        api_key=api_key,
        model=model,
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        max_tokens=max_tokens,
        request_builder=_openai_compatible_body,
        response_extractor=_openai_compatible_extract,
        truncation_checker=_openai_compatible_truncated,
    )


def _build_gemini(api_key: str, model: str, max_tokens: int) -> Provider:
    return Provider(
        name="gemini",
        api_key=api_key,
        model=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        max_tokens=max_tokens,
        request_builder=_gemini_body,
        response_extractor=_gemini_extract,
        truncation_checker=_gemini_truncated,
    )


def _build_anthropic(api_key: str, model: str, max_tokens: int) -> Provider:
    return Provider(
        name="anthropic",
        api_key=api_key,
        model=model,
        endpoint="https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        max_tokens=max_tokens,
        request_builder=_anthropic_body,
        response_extractor=_anthropic_extract,
        truncation_checker=_anthropic_truncated,
    )


def _build_openai(api_key: str, model: str, max_tokens: int) -> Provider:
    return Provider(
        name="openai",
        api_key=api_key,
        model=model,
        endpoint="https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        max_tokens=max_tokens,
        request_builder=_openai_compatible_body,
        response_extractor=_openai_compatible_extract,
        truncation_checker=_openai_compatible_truncated,
    )


def _openai_compatible_body(
    system: str, user: str, model: str, temperature: float, max_tokens: int
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def _openai_compatible_extract(data: dict[str, Any]) -> str:
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "LLM_RESPONSE_PARSE",
            f"Unexpected OpenAI-compatible response structure: {exc}. "
            f"Top-level keys: {list(data.keys())}",
        ) from exc


def _openai_compatible_truncated(data: dict[str, Any]) -> bool:
    choices = data.get("choices", [])
    if choices:
        return str(choices[0].get("finish_reason", "")) == "length"
    return False


def _gemini_body(
    system: str, user: str, model: str, temperature: float, max_tokens: int
) -> dict[str, Any]:
    return {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }


def _gemini_extract(data: dict[str, Any]) -> str:
    try:
        return str(data["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "LLM_RESPONSE_PARSE",
            f"Unexpected Gemini response structure: {exc}. Top-level keys: {list(data.keys())}",
        ) from exc


def _gemini_truncated(data: dict[str, Any]) -> bool:
    candidates = data.get("candidates", [])
    if candidates:
        return str(candidates[0].get("finishReason", "")) == "MAX_TOKENS"
    return False


def _anthropic_body(
    system: str, user: str, model: str, temperature: float, max_tokens: int
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def _anthropic_extract(data: dict[str, Any]) -> str:
    try:
        return str(data["content"][0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "LLM_RESPONSE_PARSE",
            f"Unexpected Anthropic response structure: {exc}. Top-level keys: {list(data.keys())}",
        ) from exc


def _anthropic_truncated(data: dict[str, Any]) -> bool:
    return str(data.get("stop_reason", "")) == "max_tokens"
