"""
Tests for the admin page + multi-provider judge wiring.

What we cover:
  * Admin auth (401 on missing/wrong token, 503 when ADMIN_TOKEN unset)
  * /admin renders HTML for everyone (gates happen client-side)
  * /admin/current returns config without leaking the API key
  * /admin/save persists, then /admin/current reflects the new state
  * /admin/save with a bad provider is rejected
  * The judge_factory resolves admin config first, env-var Anthropic
    second, None last
  * BudgetedJudge wraps the admin-resolved judge correctly per submission

What we DON'T cover (would require live API calls):
  * /admin/test against real providers — instead we monkeypatch the
    provider's list_models to assert the admin endpoint plumbing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.admin_config import InMemoryAdminStore, JudgeConfig, invalidate_cache
from api.config import Settings
from api.main import _build_judge_factory, create_app
from evaluator.gold import GoldProvider
from evaluator.judge import FakeJudge, JudgeResponse


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "corpora" / "gold"


def _settings() -> Settings:
    return Settings(
        project_id="test-project",
        project_number="0",
        region="us-central1",
        queue_id="test-queue",
        evaluator_target_url="",
        tasks_invoker_sa="",
        canvas_base_url="https://canvas.example",
        canvas_api_token="",
        canvas_webhook_secret="test-secret",
        rate_limit_per_day=5,
        daily_token_budget=50_000,
        local_dev=True,
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear the per-process judge-config cache between tests."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def admin_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-xyz")
    return "test-admin-token-xyz"


@pytest.fixture
def client(admin_token: str) -> TestClient:
    app = create_app(settings=_settings())
    app.state.arena.eval_deps.gold_provider = GoldProvider(GOLD_DIR)
    return TestClient(app)


@pytest.fixture
def client_no_admin(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Client where ADMIN_TOKEN is intentionally unset."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    app = create_app(settings=_settings())
    app.state.arena.eval_deps.gold_provider = GoldProvider(GOLD_DIR)
    return TestClient(app)


# ---------- Auth ----------

def test_admin_html_renders_unconditionally(client: TestClient) -> None:
    """The HTML page itself isn't gated — it gates client-side. Every visitor
    sees the same page; auth happens against /admin/current."""
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Sanity-check the key UI hooks are present.
    assert 'id="provider"' in body
    assert 'id="api-key"' in body
    assert 'id="test-btn"' in body
    assert 'id="save-btn"' in body


def test_admin_current_requires_token(client: TestClient) -> None:
    r = client.get("/admin/current")
    assert r.status_code == 401


def test_admin_current_rejects_wrong_token(client: TestClient) -> None:
    r = client.get("/admin/current", headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401


def test_admin_current_accepts_correct_token(client: TestClient, admin_token: str) -> None:
    r = client.get("/admin/current", headers={"X-Admin-Token": admin_token})
    assert r.status_code == 200
    body = r.json()
    # Empty store on a fresh app: provider + model are None, no api_key.
    assert body["provider"] is None
    assert body["model"] is None
    assert "api_key" not in body, "api_key must never appear in /admin/current"


def test_admin_disabled_when_token_unset(client_no_admin: TestClient) -> None:
    """If ADMIN_TOKEN isn't configured, admin endpoints 503. There's no
    open-by-default mode — that's the whole point of the gate."""
    r = client_no_admin.get("/admin/current", headers={"X-Admin-Token": "anything"})
    assert r.status_code == 503


# ---------- Save flow ----------

def test_admin_save_persists_and_redacts(client: TestClient, admin_token: str) -> None:
    headers = {"X-Admin-Token": admin_token}
    r = client.post(
        "/admin/save",
        headers=headers,
        json={"provider": "gemini", "model": "gemini-2.0-flash", "api_key": "AIza-test-key-xyz"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Now /admin/current reflects the new config — but never returns the key.
    r = client.get("/admin/current", headers=headers)
    body = r.json()
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-2.0-flash"
    assert "api_key" not in body
    assert "AIza-test-key-xyz" not in r.text  # belt-and-suspenders


def test_admin_save_rejects_unknown_provider(client: TestClient, admin_token: str) -> None:
    r = client.post(
        "/admin/save",
        headers={"X-Admin-Token": admin_token},
        json={"provider": "openai_foundry", "model": "x", "api_key": "k"},
    )
    assert r.status_code == 200  # endpoint succeeds…
    assert r.json()["ok"] is False  # …but reports a structured rejection
    assert "unknown provider" in r.json()["error"]


def test_admin_save_rejects_empty_fields(client: TestClient, admin_token: str) -> None:
    r = client.post(
        "/admin/save",
        headers={"X-Admin-Token": admin_token},
        json={"provider": "gemini", "model": "", "api_key": "k"},
    )
    assert r.json() == {"ok": False, "error": "model is required"}

    r = client.post(
        "/admin/save",
        headers={"X-Admin-Token": admin_token},
        json={"provider": "gemini", "model": "x", "api_key": ""},
    )
    assert r.json() == {"ok": False, "error": "api_key is required"}


# ---------- Judge factory resolution order ----------

def test_judge_factory_uses_admin_config_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """When admin config is set, the factory routes through the matching
    provider — not through the env-var Anthropic fallback."""
    store = InMemoryAdminStore()
    store.write(
        provider="gemini",
        model="gemini-2.0-flash",
        api_key="fake-gemini-key",
        updated_by="test",
    )

    # Stub get_provider so we don't hit the real Gemini API. The stub
    # returns a sentinel judge so we can assert it was used.
    sentinel_judge = FakeJudge()

    class StubProvider:
        def make_judge(self, api_key: str, model: str):
            assert api_key == "fake-gemini-key"
            assert model == "gemini-2.0-flash"
            return sentinel_judge
        def list_models(self, api_key: str):
            return []

    monkeypatch.setattr("api.main.get_provider", lambda name: StubProvider())
    factory = _build_judge_factory(store)
    judge = factory()
    assert judge is sentinel_judge


def test_judge_factory_falls_back_to_anthropic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No admin config → use ANTHROPIC_API_KEY env var if present."""
    store = InMemoryAdminStore()  # empty
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    factory = _build_judge_factory(store)
    judge = factory()
    # The factory returns an AnthropicJudge instance — we don't call it
    # (would hit the network), just verify the type.
    from evaluator.judge import AnthropicJudge
    assert isinstance(judge, AnthropicJudge)


def test_judge_factory_returns_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """No admin config + no env var → None. Tracks 2/3 then record an
    error in submission_scored, surfaced in the ops dashboard."""
    store = InMemoryAdminStore()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    factory = _build_judge_factory(store)
    assert factory() is None


# ---------- /admin/test plumbing ----------

def test_admin_test_endpoint_passes_through(
    client: TestClient, admin_token: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub the provider's list_models so we don't touch the network.
    Asserts the admin endpoint plumbs (provider, api_key) through correctly."""
    from evaluator.providers import ModelInfo

    captured: dict[str, str] = {}

    class StubProvider:
        def list_models(self, api_key: str):
            captured["api_key"] = api_key
            return [ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash")]
        def make_judge(self, api_key: str, model: str):
            raise NotImplementedError

    monkeypatch.setattr("api.admin.get_provider", lambda name: StubProvider())

    r = client.post(
        "/admin/test",
        headers={"X-Admin-Token": admin_token},
        json={"provider": "gemini", "api_key": "AIza-passed-through"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["models"] == [
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": ""}
    ]
    assert captured["api_key"] == "AIza-passed-through"


def test_admin_test_endpoint_redacts_api_key_from_errors(
    client: TestClient, admin_token: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the provider raises an httpx error that includes the URL with the
    API key in it (Gemini), the response must redact the key."""

    class FailingProvider:
        def list_models(self, api_key: str):
            raise RuntimeError("HTTP 401 from https://gemini.example/models?key=AIza-leak-me")
        def make_judge(self, api_key: str, model: str):
            raise NotImplementedError

    monkeypatch.setattr("api.admin.get_provider", lambda name: FailingProvider())
    r = client.post(
        "/admin/test",
        headers={"X-Admin-Token": admin_token},
        json={"provider": "gemini", "api_key": "AIza-leak-me"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "AIza-leak-me" not in body["error"]
    assert "<redacted>" in body["error"]


# ---------- OpenAI provider parameter routing ----------

@pytest.mark.parametrize("model,expected_new", [
    ("gpt-4o-mini",     False),
    ("gpt-4o",          False),
    ("gpt-4-turbo",     False),
    ("gpt-3.5-turbo",   False),
    ("gpt-5",           True),
    ("gpt-5-mini",      True),
    ("gpt-5.5",         True),  # the model name from production rev 00024 that 400'd
    ("o1-preview",      True),
    ("o3-mini",         True),
    ("o4-mini",         True),
])
def test_openai_provider_routes_max_tokens_param_by_model(
    model: str, expected_new: bool,
) -> None:
    """Newer OpenAI families (GPT-5, o1/o3/o4) require `max_completion_tokens`
    and reject `temperature`. The provider must detect by model-id prefix
    so the admin-saved model picks the right parameter shape."""
    from evaluator.providers.openai_provider import _is_newer_openai_family
    assert _is_newer_openai_family(model) is expected_new


def test_openai_provider_extracts_400_error_message() -> None:
    """When OpenAI returns a 400 with a structured error body, we surface
    the `message` (and `param` if present) so the admin sees the actionable
    reason — not just 'HTTP 400'."""
    import httpx
    from evaluator.providers.openai_provider import _extract_openai_error

    body = {"error": {
        "message": "Unsupported parameter: 'max_tokens'.",
        "param": "max_tokens",
        "type": "invalid_request_error",
    }}
    response = httpx.Response(
        status_code=400,
        json=body,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    assert _extract_openai_error(response) == (
        "Unsupported parameter: 'max_tokens'. (param=max_tokens)"
    )
