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
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from api.admin import (
    render_admin_html,
    require_admin,
    save_config as admin_save_config,
    serialize_current as admin_serialize_current,
    test_connection as admin_test_connection,
)
from api.admin_config import (
    AdminStore,
    FirestoreAdminStore,
    InMemoryAdminStore,
    get_active_judge_config,
)
from api.canvas import CanvasClient
from api.competition import render_competition_html
from api.competition_data import TRACKS_META, get_track
from api.config import Settings, get_settings
from api.errors import install_error_handlers
from api.landing import render_landing_html
from api.logging_config import configure_logging, get_logger
from api.queue import CloudTasksQueue, InMemoryQueue, SubmissionQueue
from api.rate_limit import (
    FirestoreRateLimiter,
    InMemoryRateLimiter,
    RateLimiter,
)
from api.schemas import Submission
from evaluator.gold import GoldProvider
from evaluator.providers import get_provider
from evaluator.runner import EvaluationDeps, run_evaluation
from api.get_started import render_get_started_html
from api.sample_payloads import SAMPLE_PAYLOADS
from evaluator.judge import AnthropicJudge, JudgeBackend
from evaluator.token_budget import (
    FirestoreTokenBudget,
    InMemoryTokenBudget,
    TokenBudgetStore,
)
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
    admin_store: AdminStore


def _build_judge_factory(admin_store: AdminStore) -> "Callable[[], JudgeBackend | None]":
    """Return a callable the runner uses to get a fresh judge per submission.

    Resolution order on each call:
      1. Admin-managed config in `admin_store` (Firestore + Secret Manager)
         — this is the v2 path. Cache hit is the common case.
      2. `ANTHROPIC_API_KEY` env var → AnthropicJudge — back-compat for
         services deployed before the admin page existed.
      3. None — Tracks 2/3 will record a `judge_unavailable` error.
    """
    def factory() -> JudgeBackend | None:
        cfg = get_active_judge_config(admin_store)
        if cfg is not None and cfg.api_key:
            try:
                return get_provider(cfg.provider).make_judge(cfg.api_key, cfg.model)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "admin_judge_factory_failed: %s — falling back to env var",
                    exc,
                )
        if os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicJudge()
        return None
    return factory


def _build_eval_deps(
    settings: Settings,
    leaderboard: LeaderboardStore,
    admin_store: AdminStore,
) -> EvaluationDeps:
    canvas: CanvasClient | None = None
    if settings.canvas_api_token or settings.local_dev:
        canvas = CanvasClient(
            base_url=settings.canvas_base_url,
            api_token=settings.canvas_api_token,
            dry_run=settings.local_dev or not settings.canvas_api_token,
        )

    # Token budget: per-student daily cap on judge-token spend. Same backend
    # split as the rate limiter — Firestore in prod, in-memory in dev/tests.
    token_budget: TokenBudgetStore = (
        InMemoryTokenBudget(daily_limit=settings.daily_token_budget)
        if settings.local_dev
        else FirestoreTokenBudget(settings.project_id, daily_limit=settings.daily_token_budget)
    )

    # Default gold dir is <repo>/corpora/gold; tests override via app.state.
    default_gold_dir = Path(__file__).resolve().parent.parent / "corpora" / "gold"
    return EvaluationDeps(
        leaderboard=leaderboard,
        gold_provider=GoldProvider(default_gold_dir),
        canvas=canvas,
        canvas_context_resolver=None,  # wired in Day 2 with the Canvas webhook
        judge=None,
        judge_factory=_build_judge_factory(admin_store),
        token_budget=token_budget,
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
    admin_store: AdminStore = (
        InMemoryAdminStore() if settings.local_dev
        else FirestoreAdminStore(settings.project_id)
    )
    eval_deps = _build_eval_deps(settings, leaderboard, admin_store)
    queue = _build_queue(settings, eval_deps)

    state = AppState()
    state.settings = settings
    state.queue = queue
    state.leaderboard = leaderboard
    state.admin_store = admin_store
    state.rate_limiter = rate_limiter
    state.eval_deps = eval_deps
    app.state.arena = state

    # ---------- Routes ----------

    def _state(app_: FastAPI = Depends(lambda: app)) -> AppState:
        return app_.state.arena  # type: ignore[no-any-return]

    @app.get("/", response_class=HTMLResponse)
    def root(st: AppState = Depends(_state)) -> str:
        # Kaggle-style card grid of all four competitions. Stats come from the
        # live leaderboard at request time so cards always show real numbers.
        per_track_stats: dict[str, dict[str, Any]] = {}
        for t in TRACKS_META:
            rows = st.leaderboard.top(t.id, limit=1000)
            students = sorted(
                {r["student_id"] for r in rows if r.get("student_id")}
            )
            top_row = rows[0] if rows else None
            per_track_stats[t.id] = {
                "submissions": len(rows),
                "students": len(students),
                "top_student": top_row["student_id"] if top_row else None,
            }
        return render_landing_html(version=app.version, per_track_stats=per_track_stats)

    @app.get("/competitions/{track_id}", response_class=HTMLResponse)
    def competition_page(track_id: str, st: AppState = Depends(_state)) -> str:
        # Per-track Kaggle-style page (Overview / Data / Code / Leaderboard /
        # Rules + persistent submit modal). Returns a graceful HTML 404 body
        # for unknown track_ids rather than the JSON {"detail":"Not Found"}.
        if get_track(track_id) is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "unknown_track_id",
                    "message": (
                        f"No competition for track_id={track_id!r}. "
                        f"Valid track_ids: {[t.id for t in TRACKS_META]}."
                    ),
                },
            )
        rows = st.leaderboard.top(track_id, limit=100)
        return render_competition_html(track_id, leaderboard_rows=rows)

    @app.get("/health")
    def health() -> dict[str, str]:
        # NOT named /healthz: Google's edge intercepts that exact path on
        # *.run.app URLs and returns its own 404 before the request reaches
        # the container. See memory/reference_cloud_run_healthz_gotcha.md.
        return {"status": "ok", "version": app.version}

    @app.get("/get-started", response_class=HTMLResponse)
    def get_started() -> str:
        # Tutorial page: per-track explainer + sample submission + curl /
        # PowerShell / Python snippets. Built from sample_payloads.SAMPLE_PAYLOADS
        # so the worked examples can never drift from the JSON served by
        # /samples/{track_id}.
        return render_get_started_html()

    # ---------- Admin routes ----------

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page() -> str:
        # The HTML is served unconditionally; the page itself prompts for
        # the admin token and gates every API call client-side via the
        # X-Admin-Token header. The /admin/* JSON endpoints enforce auth.
        return render_admin_html()

    @app.get("/admin/current")
    def admin_current(request: Request, st: AppState = Depends(_state)) -> dict:
        require_admin(request)
        return admin_serialize_current(st.admin_store)

    @app.post("/admin/test")
    def admin_test(
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> dict:
        require_admin(request)
        provider = str(body.get("provider", "")).strip()
        api_key = str(body.get("api_key", "")).strip()
        return admin_test_connection(provider=provider, api_key=api_key)

    @app.post("/admin/save")
    def admin_save(
        request: Request,
        body: dict[str, Any] = Body(...),
        st: AppState = Depends(_state),
    ) -> dict:
        require_admin(request)
        provider = str(body.get("provider", "")).strip()
        model = str(body.get("model", "")).strip()
        api_key = str(body.get("api_key", "")).strip()
        # Track who rotated the key. The admin token is a shared secret in
        # v1, so "admin" is the only useful value here. Future iterations
        # could swap in OIDC and capture the actual user.
        return admin_save_config(
            st.admin_store,
            provider=provider, model=model, api_key=api_key,
            updated_by="admin",
        )

    @app.get("/samples/{track_id}")
    def sample_payload(track_id: str) -> dict:
        sample = SAMPLE_PAYLOADS.get(track_id)
        if sample is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "unknown_track_id",
                    "message": (
                        f"No sample payload for track_id={track_id!r}. "
                        f"Valid track_ids: {sorted(SAMPLE_PAYLOADS)}."
                    ),
                },
            )
        return sample

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
