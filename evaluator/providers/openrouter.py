"""
OpenRouter judge backend.

OpenRouter is an OpenAI-compatible aggregator that proxies to many
underlying providers (Claude, GPT, Gemini, Llama, etc.) under one API
key. The wire format is identical to OpenAI's, so we delegate to the
OpenAI-compatible judge with a different `base_url`.

Models endpoint:    GET  https://openrouter.ai/api/v1/models
Generate endpoint:  POST https://openrouter.ai/api/v1/chat/completions
Auth: `Authorization: Bearer <api_key>` header.

Useful when the bootcamp wants to compare multiple model families through
one billing relationship without spreading credentials across vendors.
"""

from __future__ import annotations

import httpx

from evaluator.judge import JudgeBackend
from evaluator.providers import ModelInfo
from evaluator.providers.openai_provider import OpenAICompatJudge, _TIMEOUT

_BASE = "https://openrouter.ai/api/v1"


def list_models(api_key: str) -> list[ModelInfo]:
    """Fetch every model OpenRouter currently routes to.

    OpenRouter's /models is more informative than OpenAI's: it returns
    `{id, name, description, pricing, context_length, ...}`. We surface
    name + description so the admin can pick by capability rather than
    just ID.

    Auth-not-required for /models — the catalog is public — but we send
    the key anyway so the call doubles as a credential check.
    """
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{_BASE}/models", headers=headers)
    r.raise_for_status()
    out: list[ModelInfo] = []
    for m in (r.json().get("data") or []):
        mid = str(m.get("id") or "")
        if not mid:
            continue
        out.append(ModelInfo(
            id=mid,
            name=str(m.get("name") or mid),
            description=str(m.get("description") or "")[:140],
        ))
    out.sort(key=lambda mi: mi.id)
    return out


def make_judge(api_key: str, model: str) -> JudgeBackend:
    # OpenRouter recommends sending HTTP-Referer + X-Title for analytics.
    # Optional; we set them so traffic is identifiable.
    return OpenAICompatJudge(
        api_key=api_key,
        default_model=model,
        base_url=_BASE,
        provider_name="openrouter",
        extra_headers={
            "HTTP-Referer": "https://github.com/asukul/AI-arena",
            "X-Title": "AI Arena (D4 bootcamp)",
        },
    )
