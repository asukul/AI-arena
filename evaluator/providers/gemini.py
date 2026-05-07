"""
Google Gemini judge backend.

Uses the v1beta REST API directly via httpx (no `google-generativeai` SDK
dependency — keeps imports lean and the API surface stable).

Models endpoint:    GET  https://generativelanguage.googleapis.com/v1beta/models?key={key}
Generate endpoint:  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}

Auth: API key as the `key` query parameter on every request.
Pricing tier (Flash 2.0, as of 2026-05): generous free tier — 15 RPM,
1M input tokens/day. Suitable as the primary judge for the bootcamp.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from api.logging_config import get_logger
from evaluator.judge import JudgeBackend, JudgeResponse, _parse_score
from evaluator.providers import ModelInfo

log = get_logger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def list_models(api_key: str) -> list[ModelInfo]:
    """List Gemini models that support text generation.

    Filters to models with `generateContent` in supportedGenerationMethods —
    excludes embedding-only and vision-only variants.
    """
    if not api_key:
        raise ValueError("api_key is required")
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{_BASE}/models", params={"key": api_key})
    r.raise_for_status()
    out: list[ModelInfo] = []
    for m in (r.json().get("models") or []):
        methods = m.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        # Gemini IDs come back as "models/gemini-2.0-flash"; strip the prefix.
        full_id = str(m.get("name", ""))
        model_id = full_id.removeprefix("models/")
        if not model_id:
            continue
        out.append(ModelInfo(
            id=model_id,
            name=str(m.get("displayName") or model_id),
            description=str(m.get("description") or "")[:140],
        ))
    # Surface flagship models first so the admin's default pick is sane.
    def _sort_key(mi: ModelInfo) -> tuple[int, str]:
        rank = 1
        if "flash" in mi.id and "lite" not in mi.id: rank = 0
        elif "pro" in mi.id: rank = 0
        return (rank, mi.id)
    out.sort(key=_sort_key)
    return out


def make_judge(api_key: str, model: str) -> JudgeBackend:
    return GeminiJudge(api_key=api_key, default_model=model)


class GeminiJudge:
    """Implements `JudgeBackend.call` against the Gemini REST API.

    Mirrors the AnthropicJudge contract exactly — same retry behavior, same
    structured logging, same JudgeResponse shape — so it's a drop-in from
    the runner's perspective.
    """

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str = "gemini-2.0-flash",
        max_retries: int = 4,
        max_tokens: int = 1024,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._max_tokens = max_tokens

    def call(
        self, *, system: str, user: str, model: str | None = None
    ) -> JudgeResponse:
        chosen_model = model or self._default_model
        url = f"{_BASE}/models/{chosen_model}:generateContent"

        # Gemini doesn't have a separate "system" role; we prepend it as a
        # systemInstruction. Temperature=0 for deterministic grading.
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self._max_tokens,
            },
        }

        attempt = 0
        last_exc: Exception | None = None
        last_status: int | None = None
        data: dict[str, Any] | None = None
        while attempt < self._max_retries:
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    r = client.post(url, params={"key": self._api_key}, json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_status = r.status_code
                    raise httpx.HTTPStatusError(
                        f"gemini transient {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                data = r.json()
                break
            except (httpx.HTTPError,) as exc:
                last_exc = exc
                attempt += 1
                wait_s = 2 ** attempt
                log.warning(
                    "judge_retry",
                    attempt=attempt, wait_s=wait_s, exc=str(exc),
                    model=chosen_model, provider="gemini",
                )
                if attempt < self._max_retries:
                    time.sleep(wait_s)

        if data is None:
            raise RuntimeError(
                f"judge call failed after {self._max_retries} retries: {last_exc}"
            )

        # Extract first candidate's text. Gemini's shape:
        #   {"candidates": [{"content": {"parts": [{"text": "..."}]}}], "usageMetadata": {...}}
        raw = ""
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            raw = "".join(str(p.get("text") or "") for p in parts)

        score, reasoning = _parse_score(raw)

        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount") or 0)
        tokens_out = int(usage.get("candidatesTokenCount") or 0)

        log.info(
            "judge_call",
            provider="gemini",
            model=chosen_model,
            tokens_in=tokens_in, tokens_out=tokens_out,
            cache_read=0, cache_write=0,
            score=score,
        )

        return JudgeResponse(
            score=score,
            reasoning=reasoning,
            raw_text=raw,
            model=chosen_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
