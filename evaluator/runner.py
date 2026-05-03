"""
Evaluator dispatcher — the function that runs inside the Cloud Tasks worker.

Given a validated Submission, this:

  1. Looks up the gold dataset for the track.
  2. Dispatches to the track scorer (one entry per Track).
  3. Writes the ScoreResult to the leaderboard store.
  4. Posts the grade back to Canvas (if Canvas context is available).
  5. Returns the result so the worker handler can reply with it.

The dispatch table is the only place that needs to grow when a new track is
added. Each track scorer accepts (submission, gold) → ScoreResult.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from api.schemas import (
    ScoreResult,
    Submission,
    TRACK_HALLUCINATION,
    TRACK_META_JUDGE,
    TRACK_PROMPT_GOLF,
    TRACK_RAG,
    TrackId,
)
from evaluator.judge import JudgeBackend
from evaluator.token_budget import BudgetExceeded, BudgetedJudge, TokenBudgetStore
from evaluator.tracks.hallucination import score_hallucination
from evaluator.tracks.meta_judge import score_meta_judge
from evaluator.tracks.prompt_golf import score_prompt_golf
from evaluator.tracks.rag import score_rag

log = logging.getLogger(__name__)


# Every track scorer takes (submission, gold) and a keyword-only `judge`.
# Tracks that don't need an LLM (Track 1, Track 4) accept and ignore it so
# the dispatch loop stays uniform.
TrackScorer = Callable[..., ScoreResult]

TRACK_SCORERS: dict[str, TrackScorer] = {
    TRACK_HALLUCINATION: score_hallucination,
    TRACK_PROMPT_GOLF: score_prompt_golf,
    TRACK_RAG: score_rag,
    TRACK_META_JUDGE: score_meta_judge,
}


@dataclass
class EvaluationDeps:
    """Bundle of collaborators the evaluator needs at runtime.

    Built once at app startup (real GCP clients) or per-test (in-memory subs).
    """
    leaderboard: Any
    gold_provider: Any
    canvas: Any | None = None
    canvas_context_resolver: Callable[[Submission], dict[str, int] | None] | None = None
    judge: JudgeBackend | None = None
    token_budget: TokenBudgetStore | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def run_evaluation(submission: Submission, deps: EvaluationDeps) -> ScoreResult:
    """Score a submission end-to-end and persist the result."""
    scorer = TRACK_SCORERS.get(submission.track_id)
    if scorer is None:
        # Track id is valid (schema enforced) but no scorer wired yet.
        # Surface a friendly result so the platform doesn't crash mid-bootcamp.
        result = ScoreResult(
            submission_id=submission.submission_id,
            student_id=submission.student_id,
            track_id=submission.track_id,
            final_score=0.0,
            error=f"Track {submission.track_id!r} is not yet implemented.",
        )
        deps.leaderboard.write_result(result)
        return result

    # If a token budget is configured, wrap the judge so calls during this
    # submission are accounted to the submitter's student_id and rejected
    # once the daily limit is reached. Submissions for tracks with no LLM
    # call (Track 1, Track 4) will simply never invoke the wrapped judge.
    judge_for_run: JudgeBackend | None = deps.judge
    if deps.judge is not None and deps.token_budget is not None:
        judge_for_run = BudgetedJudge(
            inner=deps.judge,
            store=deps.token_budget,
            student_id=submission.student_id,
        )

    try:
        gold = deps.gold_provider.for_track(submission.track_id)
        result = scorer(submission, gold, judge=judge_for_run)
    except BudgetExceeded as exc:
        log.warning(
            "token_budget_exceeded student=%s submission=%s used=%d limit=%d",
            exc.student_id, submission.submission_id, exc.used, exc.limit,
        )
        result = ScoreResult(
            submission_id=submission.submission_id,
            student_id=submission.student_id,
            track_id=submission.track_id,
            final_score=0.0,
            error=(
                f"daily_token_budget_exceeded: used {exc.used}/{exc.limit} "
                f"judge tokens; resets at {exc.reset_at:%Y-%m-%d %H:%M} UTC"
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("scoring failed for %s", submission.submission_id)
        result = ScoreResult(
            submission_id=submission.submission_id,
            student_id=submission.student_id,
            track_id=submission.track_id,
            final_score=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )

    deps.leaderboard.write_result(result)

    if deps.canvas is not None and deps.canvas_context_resolver is not None:
        ctx = deps.canvas_context_resolver(submission)
        if ctx is not None:
            deps.canvas.post_grade(
                course_id=ctx["course_id"],
                assignment_id=ctx["assignment_id"],
                user_id=ctx["user_id"],
                score=result.final_score,
                comment=f"Auto-graded: {submission.track_id} = {result.final_score:.4f}",
            )

    return result
