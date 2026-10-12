"""Performance instrumentation for DB queries, Redis calls, and event-loop lag detection.

Enabled only when PERF_DEBUG_HEADERS=true (never in production by default).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# Context variables for per-request metrics
_db_query_count: ContextVar[int] = ContextVar("_db_query_count", default=0)
_db_query_time: ContextVar[float] = ContextVar("_db_query_time", default=0.0)
_redis_call_count: ContextVar[int] = ContextVar("_redis_call_count", default=0)
_redis_call_time: ContextVar[float] = ContextVar("_redis_call_time", default=0.0)
_request_start_time: ContextVar[float] = ContextVar("_request_start_time", default=0.0)

# Slow query threshold (ms)
SLOW_QUERY_THRESHOLD_MS = 100

# Whether instrumentation is enabled
_enabled = settings.ENVIRONMENT.lower() in {"local", "development", "dev"} or getattr(
    settings, "PERF_DEBUG_HEADERS", False
)


def is_enabled() -> bool:
    return _enabled


def reset_request_metrics() -> None:
    """Reset all metrics for a new request."""
    _db_query_count.set(0)
    _db_query_time.set(0.0)
    _redis_call_count.set(0)
    _redis_call_time.set(0.0)
    _request_start_time.set(time.perf_counter())


def get_db_query_count() -> int:
    return _db_query_count.get()


def get_db_query_time() -> float:
    return _db_query_time.get()


def get_redis_call_count() -> int:
    return _redis_call_count.get()


def get_redis_call_time() -> float:
    return _redis_call_time.get()


def get_request_elapsed_ms() -> float:
    start = _request_start_time.get()
    if start == 0.0:
        return 0.0
    return (time.perf_counter() - start) * 1000.0


def increment_db_query_count() -> None:
    _db_query_count.set(_db_query_count.get() + 1)


def add_db_query_time(seconds: float) -> None:
    _db_query_time.set(_db_query_time.get() + seconds)


def increment_redis_call_count() -> None:
    _redis_call_count.set(_redis_call_count.get() + 1)


def add_redis_call_time(seconds: float) -> None:
    _redis_call_time.set(_redis_call_time.get() + seconds)


def build_server_timing_header() -> str:
    """Build Server-Timing header value."""
    parts = []
    db_time = get_db_query_time() * 1000  # convert to ms
    if db_time > 0:
        parts.append(f"db;dur={db_time:.1f}")
    redis_time = get_redis_call_time() * 1000
    if redis_time > 0:
        parts.append(f"redis;dur={redis_time:.1f}")
    total = get_request_elapsed_ms()
    if total > 0:
        parts.append(f"total;dur={total:.1f}")
    return ", ".join(parts)


# SQLAlchemy event listeners for DB query instrumentation
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not is_enabled():
        return
    context._query_start_time = time.perf_counter()


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not is_enabled():
        return
    if hasattr(context, "_query_start_time"):
        elapsed = time.perf_counter() - context._query_start_time
        increment_db_query_count()
        add_db_query_time(elapsed)

        # Log slow queries
        elapsed_ms = elapsed * 1000
        if elapsed_ms > SLOW_QUERY_THRESHOLD_MS:
            # Normalize SQL for logging (remove extra whitespace, limit length)
            normalized = " ".join(statement.split())[:500]
            logger.warning(
                "SLOW QUERY (%.1fms): %s",
                elapsed_ms,
                normalized,
            )


def install_db_instrumentation(engine: Engine) -> None:
    """Install SQLAlchemy event listeners for query instrumentation."""
    if not is_enabled():
        return
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    logger.info("DB query instrumentation enabled")


# Event-loop lag detector
_lag_detector_task: asyncio.Task | None = None
_lag_detector_running = False


async def _lag_detector_loop() -> None:
    """Background task that measures event-loop lag by sleeping a short interval."""
    global _lag_detector_running
    _lag_detector_running = True
    try:
        while _lag_detector_running:
            start = time.perf_counter()
            await asyncio.sleep(0.05)  # 50ms nominal
            elapsed = time.perf_counter() - start
            lag_ms = (elapsed - 0.05) * 1000
            if lag_ms > 100:  # lag > 100ms
                logger.warning(
                    "EVENT LOOP LAG: %.1fms (expected 50ms, actual %.1fms)",
                    lag_ms,
                    elapsed * 1000,
                )
    except asyncio.CancelledError:
        pass
    finally:
        _lag_detector_running = False


def start_lag_detector() -> None:
    """Start the event-loop lag detector task."""
    global _lag_detector_task
    if not is_enabled():
        return
    if _lag_detector_task is None or _lag_detector_task.done():
        _lag_detector_task = asyncio.create_task(_lag_detector_loop())
        logger.info("Event-loop lag detector started")


def stop_lag_detector() -> None:
    """Stop the event-loop lag detector task."""
    global _lag_detector_task, _lag_detector_running
    _lag_detector_running = False
    if _lag_detector_task and not _lag_detector_task.done():
        _lag_detector_task.cancel()
        _lag_detector_task = None
        logger.info("Event-loop lag detector stopped")


# Redis call instrumentation wrapper
class InstrumentedRedisClient:
    """Wrapper around RedisClient that instruments all calls."""

    def __init__(self, redis_client):
        self._client = redis_client

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if callable(attr) and not name.startswith("_"):
            async def wrapper(*args, **kwargs):
                if not is_enabled():
                    return await attr(*args, **kwargs)
                start = time.perf_counter()
                try:
                    return await attr(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter() - start
                    increment_redis_call_count()
                    add_redis_call_time(elapsed)
            return wrapper
        return attr


def wrap_redis_client(redis_client):
    """Wrap Redis client with instrumentation if enabled."""
    if not is_enabled():
        return redis_client
    return InstrumentedRedisClient(redis_client)


# Middleware to add performance headers
class PerfHeadersMiddleware:
    """ASGI middleware that adds performance debugging headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not is_enabled():
            await self.app(scope, receive, send)
            return

        reset_request_metrics()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Add performance headers
                headers.append((b"x-db-queries", str(get_db_query_count()).encode()))
                headers.append((b"x-db-time-ms", f"{get_db_query_time() * 1000:.1f}".encode()))
                headers.append((b"x-redis-calls", str(get_redis_call_count()).encode()))
                headers.append((b"x-redis-time-ms", f"{get_redis_call_time() * 1000:.1f}".encode()))
                timing = build_server_timing_header()
                if timing:
                    headers.append((b"server-timing", timing.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)