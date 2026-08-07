"""Request timing middleware — logs slow endpoints and adds X-Process-Time header."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.timing")


class TimingMiddleware(BaseHTTPMiddleware):
    """Measure request processing time and flag slow endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        response.headers["X-Process-Time"] = f"{elapsed_ms:.1f}ms"

        path = request.url.path
        method = request.method

        # Skip noisy paths & CORS preflights
        if path in ("/health", "/favicon.ico", "/", "/docs", "/openapi.json") or method == "OPTIONS":
            return response

        if elapsed_ms > 500:
            logger.error(
                "LATENCY [%s] %s %s → %.1fms", "CRITICAL >500ms", method, path, elapsed_ms
            )
        elif elapsed_ms > 200:
            logger.warning(
                "LATENCY [%s] %s %s → %.1fms", "HIGH >200ms", method, path, elapsed_ms
            )
        elif elapsed_ms > 100:
            logger.warning(
                "LATENCY [%s] %s %s → %.1fms", "MEDIUM >100ms", method, path, elapsed_ms
            )
        elif elapsed_ms > 50:
            logger.debug(
                "LATENCY [%s] %s %s → %.1fms", "LOW >50ms", method, path, elapsed_ms
            )

        return response
