"""
Firestore writer for leaderboard data.

Document layout (one collection per logical concern, no nesting that the JS
SDK on the leaderboard page can't traverse cheaply):

  submissions/{submission_id}              ← every submission, full ScoreResult
  leaderboard/{track_id}/entries/{student_id}  ← latest-score-wins per student/track

The leaderboard subcollection is what the public Firebase-hosted page reads
in real time.  We keep it as a denormalized "current best" snapshot rather
than recomputing from `submissions/` on every page load.

Two implementations:

  FirestoreLeaderboard  — production. Lazy-imports google-cloud-firestore.
  InMemoryLeaderboard   — local dev / tests. Stores in dicts; supports the
                          same `write_result` / `top` interface.

The "best score" rule for v1 is: keep the highest final_score per
(student_id, track_id) across all submissions.  This matches Kaggle's
default: leaderboard shows your best, not your latest.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from api.schemas import ScoreResult

log = logging.getLogger(__name__)


class LeaderboardStore(Protocol):
    def write_result(self, result: ScoreResult) -> None: ...
    def top(self, track_id: str, limit: int = 100) -> list[dict[str, Any]]: ...


# ---------- In-memory implementation (dev / tests) ----------

class InMemoryLeaderboard:
    def __init__(self) -> None:
        self.submissions: dict[str, dict[str, Any]] = {}
        # (track_id, student_id) → best entry
        self.best: dict[tuple[str, str], dict[str, Any]] = {}

    def write_result(self, result: ScoreResult) -> None:
        doc = result.model_dump(mode="json")
        self.submissions[result.submission_id] = doc

        key = (result.track_id, result.student_id)
        prior = self.best.get(key)
        if prior is None or result.final_score > prior["final_score"]:
            self.best[key] = {
                "student_id": result.student_id,
                "track_id": result.track_id,
                "final_score": result.final_score,
                "submission_id": result.submission_id,
                "scored_at": doc["scored_at"],
            }

    def top(self, track_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = [v for (t, _), v in self.best.items() if t == track_id]
        rows.sort(key=lambda r: r["final_score"], reverse=True)
        return rows[:limit]


# ---------- Firestore implementation (production) ----------

class FirestoreLeaderboard:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import firestore  # lazy
            self._client = firestore.Client(project=self.project_id)
        return self._client

    def write_result(self, result: ScoreResult) -> None:
        client = self._get_client()
        doc = result.model_dump(mode="json")

        # 1. Always write the full result.
        client.collection("submissions").document(result.submission_id).set(doc)

        # 2. Update leaderboard if this beats the student's prior best.
        ref = (
            client.collection("leaderboard")
            .document(result.track_id)
            .collection("entries")
            .document(result.student_id)
        )
        snapshot = ref.get()
        prior_best = snapshot.to_dict().get("final_score") if snapshot.exists else None
        if prior_best is None or result.final_score > prior_best:
            ref.set({
                "student_id": result.student_id,
                "track_id": result.track_id,
                "final_score": result.final_score,
                "submission_id": result.submission_id,
                "scored_at": doc["scored_at"],
            })

    def top(self, track_id: str, limit: int = 100) -> list[dict[str, Any]]:
        from google.cloud import firestore  # lazy

        client = self._get_client()
        query = (
            client.collection("leaderboard")
            .document(track_id)
            .collection("entries")
            .order_by("final_score", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [doc.to_dict() for doc in query.stream()]
