"""
FastAPI app — the public entry point and the internal worker route.

Routes:

  GET  /healthz                — liveness for Cloud Run / load balancer.
  POST /submit                 — direct submission endpoint.  Validates the
                                  envelope and enqueues the work.  Returns
                                  {submission_id, task_id, status: queued}.
  POST /internal/evaluate      — Cloud Tasks worker target.  Runs the scorer
                                  inline and writes the result to the
                                  leaderboard.  Should NOT be called by the
                                  public; in production the path is protected
                                  by Cloud Tasks OIDC auth on the Cloud Run
                                  service.

The /webhooks/canvas endpoint that fronts a real Canvas Live Events
subscription is added in Day 2 polish — its auth (HMAC) and file-fetch
helpers are already built (api/auth.py, api/canvas.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from api.canvas import CanvasClient
from api.config import Settings, get_settings
from api.errors import install_error_handlers
from api.logging_config import configure_logging, get_logger
from api.queue import CloudTasksQueue, InMemoryQueue, SubmissionQueue
from api.rate_limit import (
    FirestoreRateLimiter,
    InMemoryRateLimiter,
    RateLimiter,
)
from api.schemas import Submission
from evaluator.gold import GoldProvider
from evaluator.runner import EvaluationDeps, run_evaluation
from leaderboard.firestore_client import (
    FirestoreLeaderboard,
    InMemoryLeaderboard,
    LeaderboardStore,
)


# ---------- App-level state (built once at startup) ----------

class AppState:
    settings: Settings
    queue: SubmissionQueue
    leaderboard: LeaderboardStore
    rate_limiter: RateLimiter
    eval_deps: EvaluationDeps


def _build_eval_deps(settings: Settings, leaderboard: LeaderboardStore) -> EvaluationDeps:
    canvas: CanvasClient | None = None
    if settings.canvas_api_token or settings.local_dev:
        canvas = CanvasClient(
            base_url=settings.canvas_base_url,
            api_token=settings.canvas_api_token,
            dry_run=settings.local_dev or not settings.canvas_api_token,
        )

    # Default gold dir is <repo>/corpora/gold; tests override via app.state.
    default_gold_dir = Path(__file__).resolve().parent.parent / "corpora" / "gold"
    return EvaluationDeps(
        leaderboard=leaderboard,
        gold_provider=GoldProvider(default_gold_dir),
        canvas=canvas,
        canvas_context_resolver=None,  # wired in Day 2 with the Canvas webhook
    )


def _build_queue(settings: Settings, eval_deps: EvaluationDeps) -> SubmissionQueue:
    # Prefer local in-process queue when explicitly requested OR when the
    # production env is incomplete. The fallback keeps `uvicorn api.main:app`
    # working out of the box for first-time local dev and CI.
    use_local = settings.local_dev or not settings.evaluator_target_url
    if use_local:
        if not settings.local_dev:
            logging.getLogger(__name__).warning(
                "EVALUATOR_TARGET_URL not set; using in-process queue. "
                "Set ARENA_LOCAL_DEV=1 to silence, or configure Cloud Tasks "
                "for production."
            )

        def handler(envelope: dict) -> None:
            run_evaluation(Submission.model_validate(envelope), eval_deps)

        return InMemoryQueue(handler=handler)
    return CloudTasksQueue(
        project_id=settings.project_id,
        region=settings.region,
        queue_id=settings.queue_id,
        target_url=settings.evaluator_target_url,
        invoker_sa=settings.tasks_invoker_sa,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.  Tests call this with a custom Settings."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    log.info("app_starting", project=settings.project_id, local_dev=settings.local_dev)

    app = FastAPI(title="AI Arena", version="0.1.0")
    install_error_handlers(app)

    # Wire the singleton state.
    leaderboard: LeaderboardStore = (
        InMemoryLeaderboard() if settings.local_dev
        else FirestoreLeaderboard(settings.project_id)
    )
    rate_limiter: RateLimiter = (
        InMemoryRateLimiter(limit=settings.rate_limit_per_day) if settings.local_dev
        else FirestoreRateLimiter(settings.project_id, limit=settings.rate_limit_per_day)
    )
    eval_deps = _build_eval_deps(settings, leaderboard)
    queue = _build_queue(settings, eval_deps)

    state = AppState()
    state.settings = settings
    state.queue = queue
    state.leaderboard = leaderboard
    state.rate_limiter = rate_limiter
    state.eval_deps = eval_deps
    app.state.arena = state

    # ---------- Routes ----------

    def _state(app_: FastAPI = Depends(lambda: app)) -> AppState:
        return app_.state.arena  # type: ignore[no-any-return]

    @app.get("/health")
    def health() -> dict[str, str]:
        # NOT named /healthz: Google's edge intercepts that exact path on
        # *.run.app URLs and returns its own 404 before the request reaches
        # the container. See memory/reference_cloud_run_healthz_gotcha.md.
        return {"status": "ok", "version": app.version}

    @app.post("/submit")
    def submit(envelope: Submission, st: AppState = Depends(_state)) -> dict:
        decision = st.rate_limiter.check_and_increment(envelope.student_id)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "daily_submission_limit_reached",
                    "limit": decision.limit,
                    "current": decision.current,
                    "reset_at": decision.reset_at.isoformat(),
                    "message": (
                        f"You've used {decision.current}/{decision.limit} daily "
                        f"submissions. Counter resets at {decision.reset_at:%Y-%m-%d %H:%M} UTC."
                    ),
                },
            )
        task_id = st.queue.enqueue(envelope.model_dump(mode="json"))
        return {
            "submission_id": envelope.submission_id,
            "task_id": task_id,
            "status": "queued",
            "submissions_today": decision.current,
            "daily_limit": decision.limit,
        }

    @app.post("/internal/evaluate")
    def evaluate(envelope: Submission, st: AppState = Depends(_state)) -> dict:
        result = run_evaluation(envelope, st.eval_deps)
        return {
            "submission_id": result.submission_id,
            "final_score": result.final_score,
            "error": result.error,
        }

    @app.get("/leaderboard/{track_id}")
    def leaderboard_view(
        track_id: str,
        limit: int = 100,
        st: AppState = Depends(_state),
    ) -> dict:
        if limit <= 0 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be 1..1000")
        return {"track_id": track_id, "entries": st.leaderboard.top(track_id, limit)}

    return app


# Default app for `uvicorn api.main:app`.
app = create_app()
