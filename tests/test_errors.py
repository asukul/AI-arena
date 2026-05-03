"""Tests for the friendly error response shape."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app


def _client() -> TestClient:
    settings = Settings(
        project_id="test", project_number="0", region="us-central1",
        queue_id="test-queue", evaluator_target_url="", tasks_invoker_sa="",
        canvas_base_url="https://example", canvas_api_token="",
        canvas_webhook_secret="x", rate_limit_per_day=2,
        daily_token_budget=50_000,
        local_dev=True, log_level="WARNING",
    )
    return TestClient(create_app(settings=settings))


def test_invalid_envelope_returns_friendly_422() -> None:
    response = _client().post("/submit", json={"foo": "bar"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "submission_validation_failed"
    assert isinstance(body["problems"], list)
    assert len(body["problems"]) > 0
    # Each problem should name a field and a human-readable problem.
    for p in body["problems"]:
        assert "field" in p
        assert "problem" in p


def test_rate_limit_returns_429_with_reset_at() -> None:
    client = _client()
    envelope = {
        "submission_id": "s1",
        "student_id": "asukul",
        "track_id": "hallucination_hunter",
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "track_payload": {
            "predictions": [{"claim_id": "C001", "label": "supported"}]
        },
    }
    # limit=2 in fixture; need a fresh submission_id each time
    for i in range(2):
        envelope["submission_id"] = f"s{i}"
        r = client.post("/submit", json=envelope)
        # 200 even on the 2nd; corpora gold may not match this minimal payload,
        # but enqueue happens before scoring fails internally.
        assert r.status_code == 200, r.text

    envelope["submission_id"] = "s3"
    r = client.post("/submit", json=envelope)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["error"] == "daily_submission_limit_reached"
    assert detail["limit"] == 2
    assert detail["current"] == 2
    assert "reset_at" in detail
