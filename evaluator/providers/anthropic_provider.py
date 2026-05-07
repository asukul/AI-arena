"""
Anthropic provider — thin shim around the existing AnthropicJudge.

Exists so the admin page can list "anthropic" alongside other providers
without special-casing it in the factory. The actual judge implementation
lives in `evaluator/judge.py` and uses the official `anthropic` SDK.
"""

from __future__ import annotations

import httpx

from evaluator.judge import AnthropicJudge, JudgeBackend
from evaluator.providers import ModelInfo

_BASE = "https://api.anthropic.com/v1"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def list_models(api_key: str) -> list[ModelInfo]:
    """Fetch the current Anthropic model catalog.

    The /v1/models endpoint requires authentication, so it doubles as a
    credential check — a 401/403 response means the key is bad.
    """
    if not api_key:
        raise ValueError("api_key is required")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
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
            name=str(m.get("display_name") or mid),
            description=str(m.get("type") or ""),
        ))
    # Surface the best-balanced model first ("Haiku 4.5" by name) — it's
    # the default we recommend for the judge.
    out.sort(key=lambda mi: (0 if "haiku" in mi.id else 1, mi.id), reverse=False)
    return out


def make_judge(api_key: str, model: str) -> JudgeBackend:
    judge = AnthropicJudge(api_key=api_key)
    judge.DEFAULT_MODEL = model  # type: ignore[misc]
    return judge
