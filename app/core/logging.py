"""
app/core/logging.py
-------------------
Configures the stdlib logging system for the application.

- Development : human-readable format printed to stdout
- Production  : one JSON object per line (log aggregator friendly)

Call ``setup_logging()`` once, early in the application lifespan.
Use ``get_logger(__name__)`` in every module instead of
``logging.getLogger(__name__)`` to keep imports uniform.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.config import settings

# ------------------------------------------------------------------ #
# Formatters                                                          #
# ------------------------------------------------------------------ #

_CONSOLE_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONSOLE_DATE_FMT = "%Y-%m-%d %H:%M:%S"


class _JSONFormatter(logging.Formatter):
    """Minimal single-line JSON log formatter (no extra deps required)."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


# ------------------------------------------------------------------ #
# Public API                                                          #
# ------------------------------------------------------------------ #

def setup_logging() -> None:
    """
    Configure the root logger and silence noisy third-party loggers.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    root = logging.getLogger()

    # Already configured — skip (idempotent)
    if root.handlers:
        return

    log_level: int = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    root.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if settings.is_production:
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(fmt=_CONSOLE_FMT, datefmt=_CONSOLE_DATE_FMT)
        )

    root.addHandler(handler)

    # Quiet down chatty libraries
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Usage::

        from app.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Hello from %s", __name__)
    """
    return logging.getLogger(name)
