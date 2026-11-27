"""Request timing and access logging middleware — logs API requests, status codes, and latency."""

from __future__ import annotations

import logging
import time

from app.middleware.request_id import get_current_request_id

logger = logging.getLogger("app.timing")

_QUIET_PATHS = frozenset({"/health/live", "/favicon.ico"})


def _log_request(
    method: str,
    path: str,
    status_code: int,
    elapsed_ms: float,
    request_id: str,
) -> None:
    """Emit structured request access and latency log to the application logger."""
    is_quiet = path in _QUIET_PATHS or method == "OPTIONS"

    if elapsed_ms > 500:
        logger.error(
            "API %s %s -> %s (%.1fms) [CRITICAL >500ms] | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )
    elif status_code >= 500:
        logger.error(
            "API %s %s -> %s (%.1fms) | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )
    elif elapsed_ms > 200:
        logger.warning(
            "API %s %s -> %s (%.1fms) [HIGH >200ms] | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )
    elif elapsed_ms > 100:
        logger.warning(
            "API %s %s -> %s (%.1fms) [MEDIUM >100ms] | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )
    elif is_quiet:
        logger.debug(
            "API %s %s -> %s (%.1fms) | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )
    else:
        logger.info(
            "API %s %s -> %s (%.1fms) | req=%s",
            method,
            path,
            status_code,
            elapsed_ms,
            request_id,
        )


class TimingMiddleware:
    """Measure request processing time, add X-Process-Time header, and log API requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        path = scope.get("path", "")
        method = scope.get("method", "")
        response_started = False

        def _resolve_req_id() -> str:
            req_id = get_current_request_id()
            if req_id:
                return req_id
            state = scope.get("state")
            if isinstance(state, dict) and state.get("request_id"):
                return str(state["request_id"])
            return "-"

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                headers = list(message.get("headers", []))
                headers.append((b"x-process-time", f"{elapsed_ms:.1f}ms".encode()))
                message["headers"] = headers

                status_code = int(message.get("status", 200))
                _log_request(method, path, status_code, elapsed_ms, _resolve_req_id())
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if not response_started:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                _log_request(method, path, 500, elapsed_ms, _resolve_req_id())