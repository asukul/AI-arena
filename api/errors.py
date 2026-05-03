"""
Friendly error handlers.

Pydantic's default 422 response is technically correct but unfriendly:
nested loc lists, "ctx" dicts, internal type names.  This module flattens
validation errors into a list students can act on, and gives every 5xx a
correlation id we can search Cloud Logging for.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.logging_config import get_logger

log = get_logger(__name__)


def _flatten_validation_error(exc: RequestValidationError) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        out.append({
            "field": loc or "(root)",
            "problem": err.get("msg", "invalid value"),
            "received": err.get("input"),
        })
    return out


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problems = _flatten_validation_error(exc)
        log.warning(
            "submission_validation_failed",
            path=str(request.url.path),
            problems=problems,
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": "submission_validation_failed",
                "message": (
                    "Your submission did not match the expected schema. "
                    "See `problems` for what to fix."
                ),
                "problems": problems,
            },
        )

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = uuid.uuid4().hex
        log.error(
            "unhandled_exception",
            path=str(request.url.path),
            correlation_id=correlation_id,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": (
                    "Something went wrong on our side. "
                    "Quote this id when reporting: " + correlation_id
                ),
                "correlation_id": correlation_id,
            },
        )
