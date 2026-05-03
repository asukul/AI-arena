"""
Per-student daily rate limiting.

Goal: cap submissions at N per student per UTC day so students can't
brute-force-grid-search the judge.  Default N=5, set in api/config.py.

Two implementations:

  FirestoreRateLimiter  — production. Atomic transaction against
                          rate_limits/{student_id}_{YYYY-MM-DD}.  Race-free.

  InMemoryRateLimiter   — local dev / tests. Plain dict.  Loses state on
                          restart, which is exactly what tests want.

The decision object is the same in both cases, so the /submit handler is
unaware of which backend is in play.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    current: int      # count after this request (or attempt, if denied)
    limit: int
    reset_at: datetime  # next UTC midnight when the counter rolls over


def _next_midnight_utc(today: date) -> datetime:
    return datetime.combine(
        today + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )


def _utc_today(now_fn: Callable[[], datetime]) -> date:
    return now_fn().date()


class RateLimiter(Protocol):
    limit: int
    def check_and_increment(self, student_id: str) -> RateLimitDecision: ...


# ---------- In-memory implementation ----------

class InMemoryRateLimiter:
    def __init__(
        self,
        limit: int,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.limit = limit
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._counts: dict[tuple[str, str], int] = {}

    def check_and_increment(self, student_id: str) -> RateLimitDecision:
        today = _utc_today(self._now)
        key = (student_id, today.isoformat())
        current = self._counts.get(key, 0)
        reset = _next_midnight_utc(today)
        if current >= self.limit:
            return RateLimitDecision(False, current, self.limit, reset)
        self._counts[key] = current + 1
        return RateLimitDecision(True, current + 1, self.limit, reset)


# ---------- Firestore implementation ----------

class FirestoreRateLimiter:
    """Atomic per-student daily counter in Firestore.

    Doc path: rate_limits/{student_id}_{YYYY-MM-DD}
    Doc body: {student_id, date, count, updated_at}

    Documents are tiny (4 fields) and naturally expire from relevance after
    24h; a one-line Cloud Scheduler job (Day 7) can prune them.
    """

    def __init__(self, project_id: str, limit: int) -> None:
        self.project_id = project_id
        self.limit = limit
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import firestore  # lazy
            self._client = firestore.Client(project=self.project_id)
        return self._client

    def check_and_increment(self, student_id: str) -> RateLimitDecision:
        from google.cloud import firestore  # lazy

        today = datetime.now(UTC).date()
        reset = _next_midnight_utc(today)
        doc_id = f"{student_id}_{today.isoformat()}"
        client = self._get_client()
        ref = client.collection("rate_limits").document(doc_id)

        @firestore.transactional
        def update(tx: Any) -> RateLimitDecision:
            snapshot = ref.get(transaction=tx)
            data = snapshot.to_dict() if snapshot.exists else None
            current = int(data["count"]) if data and "count" in data else 0
            if current >= self.limit:
                return RateLimitDecision(False, current, self.limit, reset)
            tx.set(ref, {
                "student_id": student_id,
                "date": today.isoformat(),
                "count": current + 1,
                "updated_at": datetime.now(UTC),
            })
            return RateLimitDecision(True, current + 1, self.limit, reset)

        return update(client.transaction())  # type: ignore[no-any-return]
