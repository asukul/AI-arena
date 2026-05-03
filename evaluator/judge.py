"""
Claude API wrapper for AI Arena judges.

All track scorers that need an LLM call go through this module. Centralizing
buys us:

  * `temperature=0` enforced — no stochastic grading.
  * Ephemeral prompt caching on the system message — every judge call within
    a track shares the same rubric, so caching cuts repeated input cost
    dramatically (Haiku 4.5: ~10% of normal input price for cached tokens).
  * Exponential backoff on transient API errors (RateLimitError,
    InternalServerError, APIConnectionError).
  * Structured token-usage logging — flows to Cloud Logging, where we can
    sum cost per-track and per-day.
  * A `FakeJudge` for tests so CI never hits the real API.

Default judge model: Claude Haiku 4.5  (fast, cheap, good enough for grading).
Re-grade model:      Claude Opus 4.7   (used on the top 10% as a sanity check).
Cross-family check:  Gemini Flash      (separate module — different SDK).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from api.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class JudgeResponse:
    score: float            # parsed score in [0.0, 1.0]
    reasoning: str          # judge's brief justification
    raw_text: str           # full text the model returned
    model: str
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int = 0   # input tokens served from prompt cache
    cache_write_tokens: int = 0  # input tokens written to prompt cache

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class JudgeBackend(Protocol):
    def call(
        self, *, system: str, user: str, model: str | None = None
    ) -> JudgeResponse: ...


# ---------- Production: Anthropic SDK ----------

class AnthropicJudge:
    DEFAULT_MODEL = "claude-haiku-4-5"
    REGRADE_MODEL = "claude-opus-4-7"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_retries: int = 4,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy import — keeps the dep optional in tests
            if not self._api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set; cannot construct AnthropicJudge"
                )
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def call(
        self, *, system: str, user: str, model: str | None = None
    ) -> JudgeResponse:
        import anthropic  # for exception classes

        chosen_model = model or self.DEFAULT_MODEL
        client = self._get_client()

        attempt = 0
        msg: Any = None
        last_exc: Exception | None = None
        while attempt < self._max_retries:
            try:
                msg = client.messages.create(
                    model=chosen_model,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    # Cache the rubric — same system prompt across many calls.
                    system=[
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user}],
                )
                break
            except (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                last_exc = exc
                attempt += 1
                wait_s = 2 ** attempt
                log.warning(
                    "judge_retry",
                    attempt=attempt, wait_s=wait_s, exc=str(exc), model=chosen_model,
                )
                if attempt < self._max_retries:
                    time.sleep(wait_s)

        if msg is None:
            raise RuntimeError(
                f"judge call failed after {self._max_retries} retries: {last_exc}"
            )

        raw = msg.content[0].text if msg.content else ""
        score, reasoning = _parse_score(raw)
        tokens_in = int(msg.usage.input_tokens or 0)
        tokens_out = int(msg.usage.output_tokens or 0)
        cache_read = int(getattr(msg.usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(msg.usage, "cache_creation_input_tokens", 0) or 0)

        log.info(
            "judge_call",
            model=chosen_model,
            tokens_in=tokens_in, tokens_out=tokens_out,
            cache_read=cache_read, cache_write=cache_write,
            score=score,
        )

        return JudgeResponse(
            score=score,
            reasoning=reasoning,
            raw_text=raw,
            model=chosen_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )


# ---------- Tests: deterministic stub ----------

class FakeJudge:
    """Test-only judge. Lookup table of (user_text → response)."""

    def __init__(self, responses: dict[str, JudgeResponse] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[dict[str, str]] = []

    def add(self, user_substring: str, response: JudgeResponse) -> None:
        self._responses[user_substring] = response

    def call(
        self, *, system: str, user: str, model: str | None = None
    ) -> JudgeResponse:
        self.calls.append({"system": system, "user": user, "model": model or ""})
        for needle, response in self._responses.items():
            if needle in user:
                return response
        # Safe default: middling score, small token bill.
        return JudgeResponse(
            score=0.5,
            reasoning="(fake judge default)",
            raw_text='{"score": 0.5, "reasoning": "(fake)"}',
            model=model or "fake-model",
            tokens_in=20, tokens_out=10,
        )


# ---------- Score parsing ----------

_SCORE_REGEX = re.compile(r'"score"\s*:\s*([0-9]*\.?[0-9]+)')
_REASONING_REGEX = re.compile(r'"reasoning"\s*:\s*"([^"]*)"')


def _parse_score(text: str) -> tuple[float, str]:
    """Extract score and reasoning from the judge's raw output.

    Strict path: full JSON parse.
    Fallback: regex out the score field.  If neither works, return 0.0 — a
    safe default that surfaces malformed judge output as a low score, rather
    than crashing the evaluator.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "score" in data:
            score = float(data["score"])
            reasoning = str(data.get("reasoning", ""))
            return _clamp01(score), reasoning
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    score_match = _SCORE_REGEX.search(text)
    reasoning_match = _REASONING_REGEX.search(text)
    if score_match:
        try:
            return _clamp01(float(score_match.group(1))), (
                reasoning_match.group(1) if reasoning_match else text
            )
        except ValueError:
            pass

    return 0.0, text


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))
