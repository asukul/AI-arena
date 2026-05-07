"""
Multi-provider judge backends.

Every provider exposes the same surface:

  PROVIDERS[name].list_models(api_key) → list[ModelInfo]
      Used by the admin page's "Test Connection" button. Doubles as a
      credential check: a successful call proves the key works.

  PROVIDERS[name].make_judge(api_key, model) → JudgeBackend
      Constructs a judge that implements the standard `JudgeBackend.call`
      protocol from `evaluator/judge.py`. Drop-in replacement for
      AnthropicJudge.

The active provider + model is read from `api/admin_config.py` at
submission time. The API key lives in Secret Manager (`judge-api-key`).
The admin page (`api/admin.py`) is the only place that writes to either.

Adding a new provider is a four-line change to PROVIDERS plus one new
module that defines `list_models` and `make_judge`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from evaluator.judge import JudgeBackend


@dataclass(frozen=True)
class ModelInfo:
    """Normalized model entry for the admin-page dropdown."""
    id: str               # the string passed to API calls (e.g. "claude-haiku-4-5")
    name: str             # human-friendly label shown in the dropdown
    description: str = "" # optional one-line context


class Provider(Protocol):
    """Each provider module implements this surface."""
    def list_models(self, api_key: str) -> list[ModelInfo]: ...
    def make_judge(self, api_key: str, model: str) -> JudgeBackend: ...


# Lazy-import each provider so missing optional deps don't break the others.
def _get_provider(name: str) -> Provider:
    if name == "anthropic":
        from evaluator.providers import anthropic_provider
        return anthropic_provider
    if name == "gemini":
        from evaluator.providers import gemini
        return gemini
    if name == "openai":
        from evaluator.providers import openai_provider
        return openai_provider
    if name == "openrouter":
        from evaluator.providers import openrouter
        return openrouter
    raise ValueError(
        f"unknown provider {name!r}. Valid: anthropic, gemini, openai, openrouter"
    )


PROVIDER_NAMES: list[str] = ["anthropic", "gemini", "openai", "openrouter"]


def get_provider(name: str) -> Provider:
    """Public accessor. Raises ValueError for unknown providers."""
    return _get_provider(name)
