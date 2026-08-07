"""Request ID and Correlation ID middleware for end-to-end API tracing.

Injects `X-Request-ID` and `X-Correlation-ID` headers into all incoming HTTP requests
and attaches them to the outgoing response.
"""

from __future__ import annotations

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware attaching request_id and correlation_id to request state and response headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id

        # Attach to request state for access inside route handlers & loggers
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Include headers in outgoing response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response
