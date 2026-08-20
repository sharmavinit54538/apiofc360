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
    """Token bucket and sliding window rate limiter with Redis backend and in-memory fallback."""

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
        forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def check_rate_limit(self, request: Request) -> tuple[bool, int, int]:
        """
        Check if request is within global rate limits.
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
        minute_count = int(minute_count) if minute_count and minute_count.isdigit() else 0

        if minute_count >= self.rate_per_minute:
            retry_after = 60 - int(now % 60)
            return False, max(1, retry_after), 0

        # Check hour window
        hour_key = f"ratelimit:{client_key}:hour:{int(now // 3600)}"
        hour_count = await self.redis.get(hour_key)
        hour_count = int(hour_count) if hour_count and hour_count.isdigit() else 0

        if hour_count >= self.rate_per_hour:
            retry_after = 3600 - int(now % 3600)
            return False, max(1, retry_after), 0

        # Increment counters
        await self.redis.set(minute_key, str(minute_count + 1), ttl_seconds=120)
        await self.redis.set(hour_key, str(hour_count + 1), ttl_seconds=7200)

        remaining = min(self.rate_per_minute - minute_count - 1, self.rate_per_hour - hour_count - 1)
        return True, 0, max(0, remaining)

    async def check_custom_rate_limit(
        self,
        request: Request,
        scope: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        """
        Check endpoint-specific rate limit with true sliding window in Redis.
        Returns: (allowed, retry_after_seconds, remaining_requests)
        """
        if not self.enabled:
            return True, 0, limit

        await self.redis.connect()
        client_key = self._get_client_key(request)
        now = time.time()
        rate_key = f"ratelimit:{scope}:{client_key}"

        # Fetch existing timestamps
        raw_val = await self.redis.get(rate_key)
        timestamps: list[float] = []
        if raw_val:
            try:
                import json
                timestamps = json.loads(raw_val)
            except Exception:
                timestamps = []

        # Filter out timestamps older than sliding window
        cutoff = now - window_seconds
        valid_timestamps = [t for t in timestamps if t > cutoff]

        if len(valid_timestamps) >= limit:
            oldest = valid_timestamps[0]
            retry_after = int(window_seconds - (now - oldest))
            return False, max(1, retry_after), 0

        # Append current timestamp and save
        valid_timestamps.append(now)
        import json
        await self.redis.set(rate_key, json.dumps(valid_timestamps), ttl_seconds=window_seconds * 2)

        remaining = max(0, limit - len(valid_timestamps))
        return True, 0, remaining


rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Strict Endpoint Rate Limiter Dependencies
# ---------------------------------------------------------------------------

async def check_login_rate_limit(request: Request) -> None:
    """Strict rate limit for /auth/login (5 requests per minute per IP)."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="auth_login", limit=settings.LOGIN_RATE_LIMIT_LIMIT, window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW
    )
    if not allowed:
        logger.warning("Login rate limit exceeded | key=%s | retry_after=%ds", rate_limiter._get_client_key(request), retry_after)
        raise RateLimitExceeded(
            detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


async def check_forgot_password_rate_limit(request: Request) -> None:
    """Strict rate limit for /auth/forgot-password (3 requests per minute per IP)."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="auth_forgot_pw", limit=3, window_seconds=60
    )
    if not allowed:
        logger.warning("Forgot password rate limit exceeded | key=%s | retry_after=%ds", rate_limiter._get_client_key(request), retry_after)
        raise RateLimitExceeded(
            detail=f"Too many password reset requests. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


async def check_otp_rate_limit(request: Request) -> None:
    """Strict rate limit for OTP verification & resend endpoints (5 requests per minute per IP)."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="auth_otp", limit=5, window_seconds=60
    )
    if not allowed:
        logger.warning("OTP rate limit exceeded | key=%s | retry_after=%ds", rate_limiter._get_client_key(request), retry_after)
        raise RateLimitExceeded(
            detail=f"Too many OTP attempts. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


async def check_onboarding_rate_limit(request: Request) -> None:
    """Rate limit for onboarding actions (5 requests per minute per IP)."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="onboarding", limit=5, window_seconds=60
    )
    if not allowed:
        logger.warning("Onboarding rate limit exceeded | key=%s | retry_after=%ds", rate_limiter._get_client_key(request), retry_after)
        raise RateLimitExceeded(
            detail=f"Too many requests. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global and path-aware rate limiting middleware."""

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

    # Specific path rate limits: path_suffix -> (limit, window_seconds, scope)
    PATH_LIMITS = {
        "/auth/login": (5, 60, "mw_auth_login"),
        "/auth/forgot-password": (3, 60, "mw_auth_forgot_pw"),
        "/auth/verify-email": (5, 60, "mw_auth_otp"),
        "/auth/resend-verification": (5, 60, "mw_auth_otp"),
        "/auth/resend-otp": (5, 60, "mw_auth_otp"),
        "/auth/verify-new-email": (5, 60, "mw_auth_otp"),
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for CORS preflights
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip rate limiting for excluded paths
        path = request.url.path
        if path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Skip for static files
        if path.startswith("/uploads/"):
            return await call_next(request)

        # Skip for websocket connections
        if path.startswith("/ws"):
            return await call_next(request)

        # Check path-specific strict limits
        for path_suffix, (limit, window, scope) in self.PATH_LIMITS.items():
            if path.endswith(path_suffix):
                allowed, retry_after, remaining = await rate_limiter.check_custom_rate_limit(
                    request, scope=scope, limit=limit, window_seconds=window
                )
                if not allowed:
                    logger.warning(
                        "Strict path rate limit exceeded for %s | path=%s | retry_after=%ds",
                        rate_limiter._get_client_key(request),
                        path,
                        retry_after,
                    )
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "success": False,
                            "message": f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                            "data": None,
                            "errors": [{"field": None, "message": f"Rate limit exceeded. Please try again in {retry_after} seconds."}],
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                break

        # Check global limit
        allowed, retry_after, remaining = await rate_limiter.check_rate_limit(request)

        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s | path=%s | retry_after=%ds",
                rate_limiter._get_client_key(request),
                path,
                retry_after,
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "message": f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                    "data": None,
                    "errors": [{"field": None, "message": f"Rate limit exceeded. Please try again in {retry_after} seconds."}],
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.API_RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def get_rate_limiter() -> RateLimiter:
    return rate_limiter