"""Global API rate limiting using Redis with in-memory fallback for local development."""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class RateLimitExceeded(HTTPException):
    def __init__(self, detail: str, retry_after: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


class RateLimiter:
    """Token bucket rate limiter with Redis backend."""

    def __init__(self):
        self.redis = get_redis_client()
        self.enabled = settings.API_RATE_LIMIT_ENABLED
        self.rate_per_minute = settings.API_RATE_LIMIT_PER_MINUTE
        self.rate_per_hour = settings.API_RATE_LIMIT_PER_HOUR
        self.burst = settings.API_RATE_LIMIT_BURST

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Prefer authenticated user ID if available
        if hasattr(request.state, "user_claims") and request.state.user_claims:
            user_id = request.state.user_claims.get("sub")
            if user_id:
                return f"user:{user_id}"

        # Fallback to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def check_rate_limit(self, request: Request) -> tuple[bool, int, int]:
        """
        Check if request is within rate limits.
        Returns: (allowed, retry_after_seconds, remaining_requests)
        """
        if not self.enabled:
            return True, 0, self.rate_per_minute

        await self.redis.connect()
        client_key = self._get_client_key(request)
        now = time.time()

        # Check minute window
        minute_key = f"ratelimit:{client_key}:minute:{int(now // 60)}"
        minute_count = await self.redis.get(minute_key)
        minute_count = int(minute_count) if minute_count else 0

        if minute_count >= self.rate_per_minute:
            retry_after = 60 - int(now % 60)
            return False, retry_after, 0

        # Check hour window
        hour_key = f"ratelimit:{client_key}:hour:{int(now // 3600)}"
        hour_count = await self.redis.get(hour_key)
        hour_count = int(hour_count) if hour_count else 0

        if hour_count >= self.rate_per_hour:
            retry_after = 3600 - int(now % 3600)
            return False, retry_after, 0

        # Increment counters
        await self.redis.set(minute_key, str(minute_count + 1), ttl_seconds=120)
        await self.redis.set(hour_key, str(hour_count + 1), ttl_seconds=7200)

        remaining = min(self.rate_per_minute - minute_count - 1, self.rate_per_hour - hour_count - 1)
        return True, 0, max(0, remaining)


rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global rate limiting middleware."""

    # Paths excluded from rate limiting
    EXCLUDED_PATHS = {
        "/health",
        "/health/ready",
        "/",
        "/favicon.ico",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Skip for static files
        if request.url.path.startswith("/uploads/"):
            return await call_next(request)

        # Skip for websocket connections
        if request.url.path.startswith("/ws"):
            return await call_next(request)

        allowed, retry_after, remaining = await rate_limiter.check_rate_limit(request)

        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s | path=%s | retry_after=%ds",
                rate_limiter._get_client_key(request),
                request.url.path,
                retry_after,
            )
            raise RateLimitExceeded(
                detail=f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                retry_after=retry_after,
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.API_RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def get_rate_limiter() -> RateLimiter:
    return rate_limiter