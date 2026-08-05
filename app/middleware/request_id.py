"""
app/middleware/request_id.py
-----------------------------
Injects a unique ``X-Request-ID`` header into every request and
echoes it back in the response so clients can correlate log entries.

If the caller already provides ``X-Request-ID`` it is preserved;
otherwise a new UUID4 is generated.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request and response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id: str = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Make it available to route handlers via request.state
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
