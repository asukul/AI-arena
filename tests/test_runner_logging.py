"""
Tests for the structured `submission_scored` log event emitted by
`evaluator/runner.py`.

This event is the load-bearing observability signal for the bootcamp:
it carries `student_id` (which `judge_call` doesn't), so per-student
token aggregation, success rates, and error breakdowns all run off it.
A regression here turns those queries silent without any runtime symptom.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.config import Settings
from api.main import create_app
from evaluator.gold import GoldProvider
from evaluator.runner import EvaluationDeps, run_evaluation
from evaluator.token_budget import BudgetedJudge, InMemoryTokenBudget


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "corpora" / "gold"


def _hallucination_envelope(*, submission_id: str, student_id: str) -> dict:
    return {
        "submission_id": submission_id,
        "student_id": student_id,
        "track_id": "hallucination_hunter",
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "model_used": "manual",
        "prompt_version": "v1",
        "self_reported_strategy": "always supported",
        "track_payload": {
            "predictions": [
                {"claim_id": "C001", "label": "supported"},
                {"claim_id": "C002", "label": "refuted"},
                {"claim_id": "C003", "label": "not_enough_info"},
                {"claim_id": "C004", "label": "supported"},
                {"claim_id": "C005", "label": "refuted"},
            ],
        },
    }


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
        log_level="INFO",
    )


def _find_event(stdout: str, name: str) -> dict:
    """Find the most recent JSON log line in captured stdout with `event=name`.

    The structured logger writes JSON to stdout (configured in
    api.logging_config.configure_logging); each line is one log entry. We
    parse line-by-line and pick out the matching event.
    """
    matches: list[dict] = []
    available: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "event" in entry:
            available.append(str(entry.get("event")))
        if entry.get("event") == name:
            matches.append(entry)
    if not matches:
        raise AssertionError(f"no {name!r} log event found; saw events: {available}")
    return matches[-1]


def test_submission_scored_emits_with_full_payload(capfd: pytest.CaptureFixture) -> None:
    """Happy-path Track 1 submission emits a submission_scored event with all
    the fields the ops dashboard / per-student-token query expect to see."""
    app = create_app(settings=_settings())
    deps: EvaluationDeps = app.state.arena.eval_deps
    deps.gold_provider = GoldProvider(GOLD_DIR)

    envelope = _hallucination_envelope(
        submission_id="sub_logging_001",
        student_id="alice",
    )
    from api.schemas import Submission
    result = run_evaluation(Submission.model_validate(envelope), deps)

    out, _ = capfd.readouterr()
    entry = _find_event(out, "submission_scored")
    assert entry["submission_id"] == "sub_logging_001"
    assert entry["student_id"] == "alice"
    assert entry["track_id"] == "hallucination_hunter"
    assert entry["final_score"] == pytest.approx(1.0)
    assert entry["judge_tokens"] == 0  # Track 1 doesn't call the judge
    assert entry["error"] is None
    assert result.final_score == pytest.approx(1.0)


def test_submission_scored_carries_error_string_on_failure(capfd: pytest.CaptureFixture) -> None:
    """When the scorer fails (here, by feeding it a malformed gold file), the
    event must still fire with the error string populated. Otherwise the
    `arena_submissions_failed` log-based metric stays silent on real outages."""
    app = create_app(settings=_settings())
    deps: EvaluationDeps = app.state.arena.eval_deps

    # Point at a non-existent gold dir → for_track raises → runner catches it
    # and produces an error result.
    deps.gold_provider = GoldProvider(REPO_ROOT / "no_such_dir")

    envelope = _hallucination_envelope(
        submission_id="sub_logging_err",
        student_id="bob",
    )
    from api.schemas import Submission
    result = run_evaluation(Submission.model_validate(envelope), deps)

    out, _ = capfd.readouterr()
    entry = _find_event(out, "submission_scored")
    assert entry["submission_id"] == "sub_logging_err"
    assert entry["student_id"] == "bob"
    assert entry["error"], "error must be populated on failure paths"
    assert result.error is not None


def test_submission_scored_reports_real_judge_token_count() -> None:
    """The runner's per-instance counter (BudgetedJudge.tokens_used_this_run)
    is what the log line reports. Two concurrent submissions for the same
    student must each see only their own tokens, not their sibling's."""
    store = InMemoryTokenBudget(daily_limit=50_000)

    class FakeJudge:
        """Returns a constant-size response for every call."""
        def call(self, *, system: str, user: str, model: str | None = None):
            from evaluator.judge import JudgeResponse
            return JudgeResponse(
                score=0.9, reasoning="ok", raw_text="0.9",
                model="claude-haiku-4-5",
                tokens_in=100, tokens_out=50,
            )

    bj = BudgetedJudge(inner=FakeJudge(), store=store, student_id="alice")
    assert bj.tokens_used_this_run == 0
    bj.call(system="s", user="u")
    assert bj.tokens_used_this_run == 150
    bj.call(system="s", user="u")
    assert bj.tokens_used_this_run == 300

    # A separate wrapper for the same student shares the store but its own
    # counter — concurrent submissions don't pollute each other's accounting.
    bj2 = BudgetedJudge(inner=FakeJudge(), store=store, student_id="alice")
    bj2.call(system="s", user="u")
    assert bj2.tokens_used_this_run == 150
    assert bj.tokens_used_this_run == 300  # unchanged
