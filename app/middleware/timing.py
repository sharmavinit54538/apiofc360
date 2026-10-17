"""Request timing middleware — logs slow endpoints and adds X-Process-Time header.
ASGI middleware for lower overhead."""

from __future__ import annotations

import logging
import time

from starlette.responses import Response

logger = logging.getLogger("app.timing")


class TimingMiddleware:
    """Measure request processing time and flag slow endpoints."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        path = scope.get("path", "")
        method = scope.get("method", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                headers = list(message.get("headers", []))
                headers.append((b"x-process-time", f"{elapsed_ms:.1f}ms".encode()))
                message["headers"] = headers

                # Skip noisy paths & CORS preflights for logging
                if path not in ("/health", "/favicon.ico", "/", "/docs", "/openapi.json") and method != "OPTIONS":
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
            await send(message)

        await self.app(scope, receive, send_wrapper)