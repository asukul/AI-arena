"""
End-to-end smoke test for the Day-1 pipeline.

  POST /submit
    → schema validates the envelope
    → InMemoryQueue invokes the worker inline
    → evaluator dispatches to Track 1 scorer
    → ScoreResult lands in InMemoryLeaderboard
    → /leaderboard/<track> returns the entry

This is the test that proves the day-1 plumbing works.  Run it before
every deploy; if it goes red, the platform is broken regardless of what
the unit tests say.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app
from evaluator.gold import GoldProvider


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
GOLD_DIR = REPO_ROOT / "corpora" / "gold"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
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
    app = create_app(settings=settings)
    # Point the gold provider at the real corpora/ directory (the same one
    # production reads from). The starter gold file matches the fixture.
    app.state.arena.eval_deps.gold_provider = GoldProvider(GOLD_DIR)
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_returns_html_landing_page(client: TestClient) -> None:
    """Bare root must return a friendly HTML page, not FastAPI's JSON 404."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "AI" in body and "Arena" in body
    # Links to the documented endpoints should be present so a curious
    # visitor can navigate without reading code.
    assert "/health" in body
    assert "/leaderboard/hallucination_hunter" in body
    assert "/docs" in body


def test_perfect_hallucination_submission_scores_one_and_lands_on_leaderboard(
    client: TestClient,
) -> None:
    envelope = json.loads((FIXTURES / "sample_hallucination.json").read_text())

    submit = client.post("/submit", json=envelope)
    assert submit.status_code == 200, submit.text
    body = submit.json()
    assert body["submission_id"] == envelope["submission_id"]
    assert body["status"] == "queued"
    assert body["task_id"].startswith("local-task-")

    board = client.get("/leaderboard/hallucination_hunter")
    assert board.status_code == 200
    entries = board.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["student_id"] == envelope["student_id"]
    assert entries[0]["final_score"] == pytest.approx(1.0)


def test_malformed_envelope_returns_422(client: TestClient) -> None:
    response = client.post("/submit", json={"foo": "bar"})
    assert response.status_code == 422


def test_internal_evaluate_runs_scorer_directly(client: TestClient) -> None:
    """Direct hit on the worker route — what Cloud Tasks does in production."""
    envelope = json.loads((FIXTURES / "sample_hallucination.json").read_text())
    response = client.post("/internal/evaluate", json=envelope)
    assert response.status_code == 200
    assert response.json()["final_score"] == pytest.approx(1.0)
    assert response.json()["error"] is None


def test_leaderboard_returns_empty_for_unknown_track(client: TestClient) -> None:
    response = client.get("/leaderboard/prompt_golf")
    assert response.status_code == 200
    assert response.json()["entries"] == []
