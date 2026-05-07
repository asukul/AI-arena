"""
OpenAI judge backend.

Uses the OpenAI Chat Completions REST API directly via httpx (no `openai`
SDK dependency). The same wire format is used by `openrouter.py` since
OpenRouter is OpenAI-compatible — that module subclasses this one.

Models endpoint:    GET  https://api.openai.com/v1/models
Generate endpoint:  POST https://api.openai.com/v1/chat/completions
Auth: `Authorization: Bearer <api_key>` header.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from api.logging_config import get_logger
from evaluator.judge import JudgeBackend, JudgeResponse, _parse_score
from evaluator.providers import ModelInfo

log = get_logger(__name__)

_BASE = "https://api.openai.com/v1"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _list_chat_models(base_url: str, api_key: str) -> list[ModelInfo]:
    """Fetch /v1/models and filter to chat-completion models.

    OpenAI's /models endpoint returns embeddings, audio, image, and chat
    models indistinguishably. We heuristic-filter to common chat families.
    """
    if not api_key:
        raise ValueError("api_key is required")
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{base_url}/models", headers=headers)
    r.raise_for_status()
    out: list[ModelInfo] = []
    for m in (r.json().get("data") or []):
        mid = str(m.get("id") or "")
        if not mid:
            continue
        # Filter to chat-shaped models. Skip embeddings, audio, vision-only,
        # moderation, and tts/whisper variants. OpenAI puts everything in
        # one list so this is a deny-list rather than an allow-list.
        if any(skip in mid for skip in (
            "embedding", "whisper", "tts", "moderation",
            "dall-e", "audio", "babbage", "davinci-002",
        )):
            continue
        out.append(ModelInfo(
            id=mid,
            name=mid,
            description=str(m.get("owned_by") or ""),
        ))
    out.sort(key=lambda mi: mi.id)
    return out


def list_models(api_key: str) -> list[ModelInfo]:
    return _list_chat_models(_BASE, api_key)


def make_judge(api_key: str, model: str) -> JudgeBackend:
    return OpenAICompatJudge(
        api_key=api_key,
        default_model=model,
        base_url=_BASE,
        provider_name="openai",
    )


class OpenAICompatJudge:
    """OpenAI-compatible chat-completion judge.

    Used directly by the OpenAI provider and (with a different base_url)
    by OpenRouter. The wire format is identical for both.
    """

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        base_url: str = _BASE,
        provider_name: str = "openai",
        max_retries: int = 4,
        max_tokens: int = 1024,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._default_model = default_model
        self._base_url = base_url.rstrip("/")
        self._provider_name = provider_name
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._extra_headers = extra_headers or {}

    def call(
        self, *, system: str, user: str, model: str | None = None
    ) -> JudgeResponse:
        chosen_model = model or self._default_model
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        body: dict[str, Any] = {
            "model": chosen_model,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        url = f"{self._base_url}/chat/completions"

        attempt = 0
        last_exc: Exception | None = None
        data: dict[str, Any] | None = None
        while attempt < self._max_retries:
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    r = client.post(url, headers=headers, json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"{self._provider_name} transient {r.status_code}",
                        request=r.request, response=r,
                    )
                r.raise_for_status()
                data = r.json()
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                attempt += 1
                wait_s = 2 ** attempt
                log.warning(
                    "judge_retry",
                    attempt=attempt, wait_s=wait_s, exc=str(exc),
                    model=chosen_model, provider=self._provider_name,
                )
                if attempt < self._max_retries:
                    time.sleep(wait_s)

        if data is None:
            raise RuntimeError(
                f"judge call failed after {self._max_retries} retries: {last_exc}"
            )

        raw = ""
        choices = data.get("choices") or []
        if choices:
            raw = str((choices[0].get("message") or {}).get("content") or "")

        score, reasoning = _parse_score(raw)

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)

        log.info(
            "judge_call",
            provider=self._provider_name,
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
