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
from fastapi.responses import HTMLResponse

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


# Static landing page for GET /. Tiny on purpose — no template engine, no
# external assets. Served by api.main:root().
_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Arena — D4 Summer 2026 Bootcamp</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; padding: 0; min-height: 100vh;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: #0c1017; color: #f5f5f7;
    }
    main { max-width: 960px; margin: 0 auto; padding: 56px 24px; }
    .accent { color: #ffc107; }
    h1 { font-size: 56px; margin: 0 0 8px 0; letter-spacing: -1px; }
    h1 .accent { display: inline; }
    .tagline { color: #a8b1bf; margin: 0 0 32px 0; font-size: 18px; }
    .card {
      background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
      padding: 24px; margin: 18px 0;
    }
    .card h2 { margin: 0 0 12px 0; font-size: 22px; color: #ffd460; }
    .card p { color: #c9d1de; margin: 0 0 12px 0; line-height: 1.55; }
    code, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px; color: #e6edf6;
    }
    code { background: #232c3d; padding: 2px 6px; border-radius: 4px; }
    a { color: #75c2ff; text-decoration: none; border-bottom: 1px dotted #4d8bd1; }
    a:hover { color: #a4d6ff; border-bottom-style: solid; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #232c3d; font-size: 14px; }
    th { color: #a8b1bf; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .pill {
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      background: #1d4d2b; color: #a6e8b6; font-size: 12px; font-weight: 600;
    }
    footer {
      max-width: 960px; margin: 0 auto; padding: 24px;
      color: #6d7787; font-size: 12px; text-align: center;
    }
  </style>
</head>
<body>
  <main>
    <h1>AI <span class="accent">Arena</span></h1>
    <p class="tagline">
      Kaggle-style competition platform for the
      <strong>D4 Summer 2026 Bootcamp</strong> &mdash; Iowa State University,
      Department of Computer Science.
      <span class="pill">v{VERSION} live</span>
    </p>

    <div class="card">
      <h2>What this service is</h2>
      <p>
        AI Arena receives student submissions for four competition tracks
        (classification, prompt-golf, RAG, build-your-own-judge), scores them
        with hidden gold data plus an LLM-as-judge, and publishes the results
        to a real-time leaderboard. The full design lives in
        <a href="https://github.com/asukul/AI-arena/blob/main/PLAN.md">PLAN.md</a>.
      </p>
    </div>

    <div class="card">
      <h2>Try the API</h2>
      <table>
        <thead>
          <tr><th>Method</th><th>Path</th><th>Purpose</th></tr>
        </thead>
        <tbody>
          <tr><td><code>GET</code></td><td><a href="/health">/health</a></td><td>Liveness probe</td></tr>
          <tr><td><code>GET</code></td><td><a href="/docs">/docs</a></td><td>Interactive Swagger UI</td></tr>
          <tr><td><code>GET</code></td><td><a href="/redoc">/redoc</a></td><td>Alternative API reference</td></tr>
          <tr><td><code>POST</code></td><td><code>/submit</code></td><td>Submit a graded entry</td></tr>
          <tr><td><code>GET</code></td><td><a href="/leaderboard/hallucination_hunter">/leaderboard/hallucination_hunter</a></td><td>Track 1 leaderboard JSON</td></tr>
          <tr><td><code>GET</code></td><td><a href="/leaderboard/prompt_golf">/leaderboard/prompt_golf</a></td><td>Track 2 leaderboard JSON</td></tr>
          <tr><td><code>GET</code></td><td><a href="/leaderboard/rag_treasure_hunt">/leaderboard/rag_treasure_hunt</a></td><td>Track 3 leaderboard JSON</td></tr>
          <tr><td><code>GET</code></td><td><a href="/leaderboard/meta_judge">/leaderboard/meta_judge</a></td><td>Track 4 leaderboard JSON</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Tracks</h2>
      <table>
        <thead><tr><th>#</th><th>Track</th><th>Metric</th></tr></thead>
        <tbody>
          <tr><td>1</td><td>Hallucination Hunter</td><td>macro-F1 vs hidden gold</td></tr>
          <tr><td>2</td><td>Prompt Golf</td><td>judge accuracy &divide; tokens spent</td></tr>
          <tr><td>3</td><td>RAG Treasure Hunt</td><td>weighted rubric (correctness 30 / faithfulness 25 / retrieval 15 / citations 15 / cost 10 / safety 5)</td></tr>
          <tr><td>4</td><td>Build Your Own AI Judge</td><td>linear-weighted Cohen&apos;s &kappa; vs instructor gold</td></tr>
        </tbody>
      </table>
    </div>
  </main>
  <footer>
    Iowa State University &middot; Department of Computer Science &middot;
    <a href="mailto:adisak.sukul@gmail.com">Adisak Sukul</a>
  </footer>
</body>
</html>
"""


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

    @app.get("/", response_class=HTMLResponse)
    def root() -> str:
        # Bare-root visitors land here. Without this route FastAPI returns
        # `{"detail":"Not Found"}` which looks broken to anyone hitting the
        # service URL in a browser. Tiny static page; no template engine.
        return _LANDING_HTML.replace("{VERSION}", app.version)

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
