"""
Centralized config — every env var the app reads is declared here, with the
documented default.  One place to look when something looks misconfigured.

Production loads from the Cloud Run service env (which itself comes from
Secret Manager for sensitive values).  Local dev loads from `.env` via
whatever loader is in use (uvicorn --env-file, direnv, etc.).

`local_dev=True` is the switch that swaps GCP clients (Cloud Tasks, Firestore,
Canvas) for in-process stubs — letting the full pipeline run on a laptop
without any GCP credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Settings:
    project_id: str
    project_number: str
    region: str

    queue_id: str
    evaluator_target_url: str
    tasks_invoker_sa: str

    canvas_base_url: str
    canvas_api_token: str
    canvas_webhook_secret: str

    rate_limit_per_day: int
    daily_token_budget: int
    local_dev: bool
    log_level: str


@cache
def get_settings() -> Settings:
    """Load settings from env once.  Cached for the process lifetime."""
    return Settings(
        project_id=os.getenv("GCP_PROJECT_ID", "ai-arena-platform"),
        project_number=os.getenv("GCP_PROJECT_NUMBER", "77646749251"),
        region=os.getenv("GCP_REGION", "us-central1"),
        queue_id=os.getenv("TASKS_QUEUE_ID", "d4-arena-submissions"),
        evaluator_target_url=os.getenv("EVALUATOR_TARGET_URL", ""),
        tasks_invoker_sa=os.getenv("TASKS_INVOKER_SA", ""),
        canvas_base_url=os.getenv("CANVAS_BASE_URL", "https://canvas.iastate.edu"),
        canvas_api_token=os.getenv("CANVAS_API_TOKEN", ""),
        canvas_webhook_secret=os.getenv("CANVAS_WEBHOOK_SECRET", ""),
        rate_limit_per_day=int(os.getenv("RATE_LIMIT_PER_DAY", "5")),
        daily_token_budget=int(os.getenv("DAILY_TOKEN_BUDGET", "50000")),
        local_dev=os.getenv("ARENA_LOCAL_DEV", "0") == "1",
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def reset_settings_cache() -> None:
    """Tests use this to pick up monkeypatched env vars."""
    get_settings.cache_clear()
