"""
Per-student daily token-budget guardrail (PLAN.md Day 7).

Goal: cap the number of judge tokens a single student can consume per UTC
day. Default 50,000 tokens — generous enough for normal experimentation,
strict enough that one runaway loop can't drain the bootcamp's Anthropic
budget.

Two storage backends, mirroring the rate-limit module:

  FirestoreTokenBudget — production. One Firestore doc per
                          (student, day), updated atomically.

  InMemoryTokenBudget   — tests and local dev. Plain dict, resets on
                          process restart.

Wiring:

  1. `EvaluationDeps` holds an optional `token_budget` store.
  2. The runner wraps the configured judge in `BudgetedJudge` per
     submission, scoping the per-call accounting to the submitter's
     `student_id`.
  3. When a call would push the day's spend past `daily_limit_tokens`,
     `BudgetExceeded` is raised. The runner catches it and surfaces a
     friendly `ScoreResult` with `error="daily_token_budget_exceeded"`
     instead of a stack trace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from evaluator.judge import JudgeBackend, JudgeResponse


_DEFAULT_DAILY_LIMIT_TOKENS = 50_000


# ---------- Exceptions ----------

class BudgetExceeded(Exception):
    """Raised when a judge call would exceed the per-student daily budget."""

    def __init__(self, *, student_id: str, used: int, limit: int, reset_at: datetime) -> None:
        self.student_id = student_id
        self.used = used
        self.limit = limit
        self.reset_at = reset_at
        super().__init__(
            f"Student {student_id!r} has used {used}/{limit} daily judge tokens; "
            f"counter resets at {reset_at:%Y-%m-%d %H:%M} UTC."
        )


# ---------- Time helpers (shared with rate_limit) ----------

def _next_midnight_utc(today: date) -> datetime:
    return datetime.combine(
        today + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )


# ---------- Storage protocol ----------

class TokenBudgetStore(Protocol):
    daily_limit: int
    def tokens_used_today(self, student_id: str) -> int: ...
    def record_tokens(self, student_id: str, tokens: int) -> int: ...
    def reset_at(self) -> datetime: ...


# ---------- In-memory implementation ----------

class InMemoryTokenBudget:
    def __init__(
        self,
        *,
        daily_limit: int = _DEFAULT_DAILY_LIMIT_TOKENS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.daily_limit = daily_limit
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._counts: dict[tuple[str, str], int] = {}

    def _key(self, student_id: str) -> tuple[str, str]:
        today = self._now().date().isoformat()
        return (student_id, today)

    def tokens_used_today(self, student_id: str) -> int:
        return self._counts.get(self._key(student_id), 0)

    def record_tokens(self, student_id: str, tokens: int) -> int:
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        key = self._key(student_id)
        self._counts[key] = self._counts.get(key, 0) + tokens
        return self._counts[key]

    def reset_at(self) -> datetime:
        return _next_midnight_utc(self._now().date())


# ---------- Firestore implementation ----------

class FirestoreTokenBudget:
    """Atomic per-student daily token counter in Firestore.

    Doc path: token_budgets/{student_id}_{YYYY-MM-DD}
    Doc body: {student_id, date, tokens_used, updated_at}
    """

    def __init__(
        self,
        project_id: str,
        *,
        daily_limit: int = _DEFAULT_DAILY_LIMIT_TOKENS,
    ) -> None:
        self.project_id = project_id
        self.daily_limit = daily_limit
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import firestore  # lazy
            self._client = firestore.Client(project=self.project_id)
        return self._client

    def _doc_id(self, student_id: str) -> str:
        today = datetime.now(UTC).date().isoformat()
        return f"{student_id}_{today}"

    def tokens_used_today(self, student_id: str) -> int:
        client = self._get_client()
        snap = client.collection("token_budgets").document(self._doc_id(student_id)).get()
        if not snap.exists:
            return 0
        data = snap.to_dict() or {}
        return int(data.get("tokens_used", 0))

    def record_tokens(self, student_id: str, tokens: int) -> int:
        from google.cloud import firestore  # lazy

        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        today = datetime.now(UTC).date()
        client = self._get_client()
        ref = client.collection("token_budgets").document(self._doc_id(student_id))

        @firestore.transactional
        def update(tx: Any) -> int:
            snap = ref.get(transaction=tx)
            data = snap.to_dict() if snap.exists else None
            used = int(data["tokens_used"]) if data and "tokens_used" in data else 0
            new_used = used + tokens
            tx.set(ref, {
                "student_id": student_id,
                "date": today.isoformat(),
                "tokens_used": new_used,
                "updated_at": datetime.now(UTC),
            })
            return new_used

        return update(client.transaction())  # type: ignore[no-any-return]

    def reset_at(self) -> datetime:
        return _next_midnight_utc(datetime.now(UTC).date())


# ---------- Budget-enforcing judge wrapper ----------

@dataclass
class BudgetedJudge:
    """Wraps a `JudgeBackend` and rejects calls that would overflow the
    student's daily token budget.

    Pre-call check uses *current usage*; the actual cost of this call is
    only known after the call returns. We accept that small over-shoot:
    if a student is at 49,950/50,000 and makes a call costing 200 tokens,
    they end up at 50,150 — within the noise of any real budget. The
    next call is then refused.

    `tokens_used_this_run` is a per-instance counter so the runner can log
    "this submission spent N tokens" without race-reading the shared store
    (concurrent submissions for the same student would otherwise read each
    other's deltas).
    """

    inner: JudgeBackend
    store: TokenBudgetStore
    student_id: str
    tokens_used_this_run: int = 0

    def call(self, *, system: str, user: str, model: str | None = None) -> JudgeResponse:
        used = self.store.tokens_used_today(self.student_id)
        if used >= self.store.daily_limit:
            raise BudgetExceeded(
                student_id=self.student_id,
                used=used,
                limit=self.store.daily_limit,
                reset_at=self.store.reset_at(),
            )
        response = self.inner.call(system=system, user=user, model=model)
        self.store.record_tokens(self.student_id, response.total_tokens)
        self.tokens_used_this_run += response.total_tokens
        return response
