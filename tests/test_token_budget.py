"""
Per-student daily token-budget guardrail (PLAN.md Day 7).

Covers:
  * the in-memory store math (record, day rollover, reset_at)
  * the BudgetedJudge wrapper (allow, reject, token bookkeeping)
  * the runner integration (BudgetExceeded → friendly ScoreResult)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.schemas import Submission
from evaluator.judge import FakeJudge, JudgeResponse
from evaluator.runner import EvaluationDeps, run_evaluation
from evaluator.token_budget import (
    BudgetExceeded,
    BudgetedJudge,
    InMemoryTokenBudget,
)
from leaderboard.firestore_client import InMemoryLeaderboard


# ---------- In-memory store ----------

def test_initial_usage_is_zero() -> None:
    store = InMemoryTokenBudget(daily_limit=1000)
    assert store.tokens_used_today("alice") == 0


def test_record_accumulates_per_student() -> None:
    store = InMemoryTokenBudget(daily_limit=1000)
    store.record_tokens("alice", 100)
    store.record_tokens("alice", 250)
    store.record_tokens("bob", 50)
    assert store.tokens_used_today("alice") == 350
    assert store.tokens_used_today("bob") == 50


def test_negative_record_raises() -> None:
    store = InMemoryTokenBudget()
    with pytest.raises(ValueError, match="non-negative"):
        store.record_tokens("alice", -1)


def test_day_rollover_resets_counter() -> None:
    """A new UTC day means a fresh counter — students get their budget back."""
    times = [datetime(2026, 5, 3, 23, 0, tzinfo=UTC)]
    store = InMemoryTokenBudget(daily_limit=1000, now_fn=lambda: times[0])
    store.record_tokens("alice", 800)
    assert store.tokens_used_today("alice") == 800
    # Roll forward into the next UTC day.
    times[0] = datetime(2026, 5, 4, 0, 1, tzinfo=UTC)
    assert store.tokens_used_today("alice") == 0


def test_reset_at_is_next_utc_midnight() -> None:
    fixed = datetime(2026, 5, 3, 14, 30, tzinfo=UTC)
    store = InMemoryTokenBudget(now_fn=lambda: fixed)
    assert store.reset_at() == datetime(2026, 5, 4, 0, 0, tzinfo=UTC)


# ---------- BudgetedJudge wrapper ----------

def _judge(score: float = 0.7, tokens_in: int = 30, tokens_out: int = 10) -> FakeJudge:
    fake = FakeJudge()
    fake.add("", JudgeResponse(
        score=score, reasoning="canned",
        raw_text=f'{{"score": {score}}}',
        model="fake", tokens_in=tokens_in, tokens_out=tokens_out,
    ))
    return fake


def test_budgeted_judge_passes_through_when_within_budget() -> None:
    inner = _judge(tokens_in=30, tokens_out=20)
    store = InMemoryTokenBudget(daily_limit=1000)
    bj = BudgetedJudge(inner=inner, store=store, student_id="alice")
    response = bj.call(system="sys", user="user")
    assert response.score == pytest.approx(0.7)
    assert store.tokens_used_today("alice") == 50  # 30 + 20


def test_budgeted_judge_blocks_when_already_at_limit() -> None:
    inner = _judge()
    store = InMemoryTokenBudget(daily_limit=100)
    store.record_tokens("alice", 100)  # already at the cap
    bj = BudgetedJudge(inner=inner, store=store, student_id="alice")
    with pytest.raises(BudgetExceeded) as ei:
        bj.call(system="sys", user="user")
    assert ei.value.used == 100
    assert ei.value.limit == 100
    assert ei.value.student_id == "alice"
    # And the inner judge should not have been called.
    assert len(inner.calls) == 0


def test_budgeted_judge_allows_small_overshoot_then_blocks_next() -> None:
    """At 49,950/50,000, a 200-token call lands at 50,150 (within noise),
    and the *next* call is the one that gets refused."""
    inner = _judge(tokens_in=150, tokens_out=50)
    store = InMemoryTokenBudget(daily_limit=50_000)
    store.record_tokens("alice", 49_950)
    bj = BudgetedJudge(inner=inner, store=store, student_id="alice")

    # First call still allowed (was at 49,950 < 50,000 pre-call).
    bj.call(system="sys", user="user")
    assert store.tokens_used_today("alice") == 50_150

    # Second call rejected — already past the limit.
    with pytest.raises(BudgetExceeded):
        bj.call(system="sys", user="user")


def test_per_student_isolation() -> None:
    """One student going over budget doesn't block another."""
    inner = _judge()
    store = InMemoryTokenBudget(daily_limit=100)
    store.record_tokens("alice", 100)
    bj_alice = BudgetedJudge(inner=inner, store=store, student_id="alice")
    bj_bob   = BudgetedJudge(inner=inner, store=store, student_id="bob")
    with pytest.raises(BudgetExceeded):
        bj_alice.call(system="s", user="u")
    # bob is untouched.
    bj_bob.call(system="s", user="u")
    assert store.tokens_used_today("bob") > 0


# ---------- Runner integration ----------

def _hallucination_submission(student_id: str = "asukul") -> Submission:
    """Track-1 submission — no judge call, so the budget should not move
    even when a wrapped judge is configured."""
    return Submission.model_validate({
        "submission_id": "sub_test",
        "student_id": student_id,
        "track_id": "hallucination_hunter",
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "track_payload": {"predictions": [{"claim_id": "C1", "label": "supported"}]},
    })


def _golf_submission(student_id: str = "asukul") -> Submission:
    """Track-2 submission — does call the judge."""
    return Submission.model_validate({
        "submission_id": "sub_test",
        "student_id": student_id,
        "track_id": "prompt_golf",
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "track_payload": {
            "prompt_template": "Answer:",
            "samples": [{"input": "Q1", "output": "A1"}],
        },
    })


class _StubGold:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
    def for_track(self, _track: str) -> dict:
        return self._payload


def test_track1_does_not_consume_token_budget() -> None:
    """Track 1 has no LLM call; budget should remain at 0 even when a
    wrapped judge is wired."""
    store = InMemoryTokenBudget(daily_limit=100)
    deps = EvaluationDeps(
        leaderboard=InMemoryLeaderboard(),
        gold_provider=_StubGold({"C1": "supported"}),
        judge=_judge(),
        token_budget=store,
    )
    result = run_evaluation(_hallucination_submission(), deps)
    assert result.error is None
    assert result.final_score == pytest.approx(1.0)
    assert store.tokens_used_today("asukul") == 0


def test_track2_consumes_token_budget() -> None:
    """Each Prompt Golf judge call adds to the budget store."""
    store = InMemoryTokenBudget(daily_limit=10_000)
    inner = _judge(tokens_in=40, tokens_out=15)
    deps = EvaluationDeps(
        leaderboard=InMemoryLeaderboard(),
        gold_provider=_StubGold({
            "items": [{"input": "Q1", "expected_output": "A1"}],
            "baseline_tokens_per_sample": 50,
        }),
        judge=inner,
        token_budget=store,
    )
    result = run_evaluation(_golf_submission(), deps)
    assert result.error is None
    # One sample → one judge call → 55 tokens charged.
    assert store.tokens_used_today("asukul") == 55


def test_runner_surfaces_friendly_error_when_budget_exceeded() -> None:
    """When the budget is already drained, the runner should NOT crash —
    it produces a ScoreResult with a clear `error` message."""
    store = InMemoryTokenBudget(daily_limit=10)
    store.record_tokens("asukul", 10)  # pre-drain
    leaderboard = InMemoryLeaderboard()
    deps = EvaluationDeps(
        leaderboard=leaderboard,
        gold_provider=_StubGold({
            "items": [{"input": "Q1", "expected_output": "A1"}],
            "baseline_tokens_per_sample": 50,
        }),
        judge=_judge(),
        token_budget=store,
    )
    result = run_evaluation(_golf_submission(), deps)
    assert result.error is not None
    assert "daily_token_budget_exceeded" in result.error
    assert result.final_score == 0.0
    # The full result (with the error string) is persisted to submissions/
    # for retrieval. The denormalized leaderboard "best entry" view stores
    # only score-relevant fields, so we read from `submissions` here.
    stored = leaderboard.submissions[result.submission_id]
    assert stored["error"] == result.error
