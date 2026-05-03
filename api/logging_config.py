"""
Structured JSON logging for Cloud Logging.

Cloud Logging on Cloud Run auto-parses stdout JSON into structured fields
when certain keys are present:

  severity  → log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
  message   → primary text
  timestamp → ISO 8601 UTC

Anything else becomes a structured field under `jsonPayload`, queryable in
Logs Explorer.  This is why we write JSON to stdout instead of the default
human-readable format: it's free observability with zero extra cost.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def _level_to_cloud_logging_severity(
    _logger: Any,
    _name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    if "level" in event_dict:
        event_dict["severity"] = event_dict.pop("level").upper()
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Idempotent configuration; safe to call multiple times."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _level_to_cloud_logging_severity,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Mirror stdlib loggers (fastapi, uvicorn, google.cloud) into structlog.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(message)s")  # structlog handles formatting
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
