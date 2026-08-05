"""
app/middleware/logging.py
--------------------------
Structured HTTP access-log middleware.

Logs method, path, status code, latency (ms), and request ID for
every inbound request.  In development the output is human-readable;
in production it integrates with the JSON formatter in core/logging.py.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import get_logger

logger = get_logger(__name__)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing information."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start: float = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms: float = round((time.perf_counter() - start) * 1_000, 2)

        request_id: str = getattr(request.state, "request_id", "-")

        logger.info(
            "%s %s %s  %.2fms  req_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
