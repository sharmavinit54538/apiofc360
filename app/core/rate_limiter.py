"""Global API rate limiting using Redis with atomic Lua scripts and in-memory fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Optional

from fastapi import Request, HTTPException, status
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


# Lua script for atomic fixed-window rate limiting (minute + hour)
# Returns: [allowed (0/1), retry_after_seconds, remaining_minute, remaining_hour]
RATE_LIMIT_SCRIPT = """
local minute_key = KEYS[1]
local hour_key = KEYS[2]
local minute_limit = tonumber(ARGV[1])
local hour_limit = tonumber(ARGV[2])
local minute_ttl = tonumber(ARGV[3])
local hour_ttl = tonumber(ARGV[4])

local minute_count = tonumber(redis.call('GET', minute_key) or '0')
local hour_count = tonumber(redis.call('GET', hour_key) or '0')

if minute_count >= minute_limit then
    local ttl = redis.call('TTL', minute_key)
    return {0, ttl > 0 and ttl or 60, 0, hour_limit - hour_count}
end

if hour_count >= hour_limit then
    local ttl = redis.call('TTL', hour_key)
    return {0, ttl > 0 and ttl or 3600, minute_limit - minute_count, 0}
end

local new_minute = redis.call('INCR', minute_key)
if new_minute == 1 then
    redis.call('EXPIRE', minute_key, minute_ttl)
end

local new_hour = redis.call('INCR', hour_key)
if new_hour == 1 then
    redis.call('EXPIRE', hour_key, hour_ttl)
end

local remaining_minute = minute_limit - new_minute
local remaining_hour = hour_limit - new_hour
local remaining = math.min(remaining_minute, remaining_hour)
return {1, 0, remaining, remaining}
"""

# Lua script for sliding window rate limiting
# Returns: [allowed (0/1), retry_after_seconds, remaining]
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local cutoff = now - window
local timestamps = redis.call('ZRANGEBYSCORE', key, cutoff, '+inf')
local count = #timestamps

if count >= limit then
    local oldest = tonumber(timestamps[1])
    local retry_after = math.ceil(window - (now - oldest))
    return {0, math.max(1, retry_after), 0}
end

redis.call('ZADD', key, now, now .. '-' .. math.random(1000000))
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
redis.call('EXPIRE', key, ttl)

local remaining = limit - count - 1
return {1, 0, remaining}
"""


class RateLimiter:
    """Token bucket and sliding window rate limiter with Redis backend and in-memory fallback.
    
    Uses atomic Lua scripts for all Redis operations to prevent race conditions.
    General API limiter fails open on Redis timeout/error; strict limiters (login, OTP) remain strict.
    """

    def __init__(self, redis_client=None):
        self._redis_client = redis_client
        self.enabled = settings.API_RATE_LIMIT_ENABLED
        self.rate_per_minute = settings.API_RATE_LIMIT_PER_MINUTE
        self.rate_per_hour = settings.API_RATE_LIMIT_PER_HOUR
        self.burst = settings.API_RATE_LIMIT_BURST
        self._rate_limit_sha: Optional[str] = None
        self._sliding_window_sha: Optional[str] = None
        self._redis_timeout = 0.1  # 100ms timeout for Redis calls
        self._memory_cache: dict[str, list[float]] = {}

    def reset(self) -> None:
        """Reset in-memory rate limit cache (primarily for tests)."""
        self._memory_cache.clear()

    def _check_memory_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """In-memory sliding window rate limiter fallback when Redis is unavailable."""
        now = time.time()
        cutoff = now - window_seconds
        
        # Periodic cleanup if cache grows large
        if len(self._memory_cache) > 5000:
            stale_keys = [k for k, v in self._memory_cache.items() if not v or v[-1] <= cutoff]
            for k in stale_keys:
                self._memory_cache.pop(k, None)

        history = [ts for ts in self._memory_cache.get(key, []) if ts > cutoff]
        if len(history) >= limit:
            oldest = history[0]
            retry_after = max(1, math.ceil(window_seconds - (now - oldest)))
            self._memory_cache[key] = history
            return False, retry_after, 0

        history.append(now)
        self._memory_cache[key] = history
        remaining = max(0, limit - len(history))
        return True, 0, remaining


    @property
    def redis(self):
        if self._redis_client:
            return self._redis_client
        from app.core.redis_client import get_redis_client
        return get_redis_client()

    async def _load_scripts(self) -> None:
        """Load Lua scripts into Redis and cache their SHAs."""
        if self._rate_limit_sha and self._sliding_window_sha:
            return
        r = self.redis
        if not r._connected or not r._redis:
            return
        try:
            self._rate_limit_sha = await r._redis.script_load(RATE_LIMIT_SCRIPT)
            self._sliding_window_sha = await r._redis.script_load(SLIDING_WINDOW_SCRIPT)
        except Exception as e:
            logger.warning("Failed to load rate limit Lua scripts: %s", e)

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        if hasattr(request.state, "user_claims") and request.state.user_claims:
            user_id = request.state.user_claims.get("sub")
            if user_id:
                return f"user:{user_id}"

        forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def _execute_with_timeout(self, coro, fail_open: bool = False, default_allowed: bool = True):
        """Execute a Redis operation with timeout, with configurable fail behavior."""
        try:
            return await asyncio.wait_for(coro, timeout=self._redis_timeout)
        except asyncio.TimeoutError:
            logger.warning("Redis rate limit operation timed out (fail_open=%s)", fail_open)
            if fail_open:
                return default_allowed
            raise
        except Exception as e:
            logger.warning("Redis rate limit operation failed: %s (fail_open=%s)", e, fail_open)
            if fail_open:
                return default_allowed
            raise

    async def check_rate_limit(self, request: Request) -> tuple[bool, int, int]:
        """
        Check if request is within global rate limits using atomic Lua script.
        Returns: (allowed, retry_after_seconds, remaining_requests)
        Fail-open for general API limiter.
        """
        if not self.enabled:
            return True, 0, self.rate_per_minute

        client_key = self._get_client_key(request)
        now = time.time()
        minute_key = f"ratelimit:{client_key}:minute:{int(now // 60)}"
        hour_key = f"ratelimit:{client_key}:hour:{int(now // 3600)}"

        r = self.redis
        if not r._connected or not r._redis:
            # Redis not available - fail open for general limiter
            logger.debug("Redis not connected, failing open for general rate limiter")
            return True, 0, self.rate_per_minute

        await self._load_scripts()

        try:
            result = await self._execute_with_timeout(
                r._redis.evalsha(
                    self._rate_limit_sha,
                    2, minute_key, hour_key,
                    self.rate_per_minute, self.rate_per_hour, 120, 7200
                ),
                fail_open=True,
                default_allowed=True
            )
            
            if result is True:  # fail_open returned True
                return True, 0, self.rate_per_minute
            
            allowed, retry_after, remaining_minute, remaining_hour = result
            remaining = min(remaining_minute, remaining_hour)
            return bool(allowed), int(retry_after) if retry_after else 0, max(0, int(remaining))
            
        except Exception as e:
            logger.warning("Rate limit check failed, failing open: %s", e)
            return True, 0, self.rate_per_minute

    async def check_custom_rate_limit(
        self,
        request: Request,
        scope: str,
        limit: int,
        window_seconds: int = 60,
        fail_open: bool = False,
    ) -> tuple[bool, int, int]:
        """
        Check endpoint-specific rate limit with sliding window using atomic Lua script.
        Returns: (allowed, retry_after_seconds, remaining_requests)
        
        fail_open: if True, allow request on Redis failure (for general API).
                   if False, deny request on Redis failure (for strict limiters like login).
        """
        if not self.enabled:
            return True, 0, limit

        client_key = self._get_client_key(request)
        now = time.time()
        rate_key = f"ratelimit:{scope}:{client_key}"
        ttl = window_seconds * 2

        r = self.redis
        if not r._connected or not r._redis:
            if fail_open:
                logger.debug("Redis not connected, failing open for %s rate limiter", scope)
                return True, 0, limit
            logger.debug("Redis not connected, using in-memory sliding window fallback for %s rate limiter", scope)
            return self._check_memory_rate_limit(rate_key, limit, window_seconds)

        await self._load_scripts()

        try:
            result = await self._execute_with_timeout(
                r._redis.evalsha(
                    self._sliding_window_sha,
                    1, rate_key,
                    limit, window_seconds, int(now * 1000), ttl  # use ms precision
                ),
                fail_open=fail_open,
                default_allowed=True
            )
            
            if result is True:  # fail_open returned True
                return True, 0, limit
            
            allowed, retry_after, remaining = result
            return bool(allowed), int(retry_after) if retry_after else 0, max(0, int(remaining))
            
        except Exception as e:
            logger.warning("Custom rate limit check failed for %s: %s (fail_open=%s)", scope, e, fail_open)
            if fail_open:
                return True, 0, limit
            return self._check_memory_rate_limit(rate_key, limit, window_seconds)


# Global rate limiter instance
rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Strict Endpoint Rate Limiter Dependencies (fail_open=False - strict)
# ---------------------------------------------------------------------------

async def check_login_rate_limit(request: Request) -> None:
    """Strict rate limit for /auth/login (5 requests per minute per IP)."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="auth_login", limit=settings.LOGIN_RATE_LIMIT_LIMIT, 
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW, fail_open=False
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
        request, scope="auth_forgot_pw", limit=3, window_seconds=60, fail_open=False
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
        request, scope="auth_otp", limit=5, window_seconds=60, fail_open=False
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
        request, scope="onboarding", limit=5, window_seconds=60, fail_open=False
    )
    if not allowed:
        logger.warning("Onboarding rate limit exceeded | key=%s | retry_after=%ds", rate_limiter._get_client_key(request), retry_after)
        raise RateLimitExceeded(
            detail=f"Too many requests. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


# ---------------------------------------------------------------------------
# ASGI Middleware (replaces BaseHTTPMiddleware for lower overhead)
# ---------------------------------------------------------------------------

class RateLimitMiddleware:
    """Global and path-aware rate limiting ASGI middleware.
    
    Lower overhead than BaseHTTPMiddleware, doesn't interfere with streaming/background tasks.
    """

    # Paths excluded from rate limiting
    EXCLUDED_PATHS = {
        "/health", "/health/ready", "/", "/favicon.ico",
        "/docs", "/redoc", "/openapi.json", "/api/v1/openapi.json", "/api/v2/openapi.json",
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

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip rate limiting for CORS preflights
        method = scope.get("method", "")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        
        # Skip rate limiting for excluded paths
        if path in self.EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        # Skip for static files and websockets
        if path.startswith("/uploads/") or path.startswith("/ws"):
            await self.app(scope, receive, send)
            return

        # Create a minimal request-like object for rate limiting
        request = Request(scope, receive)

        # Check path-specific strict limits (strict - fail_closed)
        for path_suffix, (limit, window, scope_name) in self.PATH_LIMITS.items():
            if path.endswith(path_suffix):
                allowed, retry_after, remaining = await rate_limiter.check_custom_rate_limit(
                    request, scope=scope_name, limit=limit, window_seconds=window, fail_open=False
                )
                if not allowed:
                    logger.warning(
                        "Strict path rate limit exceeded for %s | path=%s | retry_after=%ds",
                        rate_limiter._get_client_key(request), path, retry_after
                    )
                    response = Response(
                        content=json.dumps({
                            "success": False,
                            "message": f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                            "data": None,
                            "errors": [{"field": None, "message": f"Rate limit exceeded. Please try again in {retry_after} seconds."}],
                        }),
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        media_type="application/json",
                        headers={"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send)
                    return
                break

        # Check global limit (fail-open)
        allowed, retry_after, remaining = await rate_limiter.check_rate_limit(request)

        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s | path=%s | retry_after=%ds",
                rate_limiter._get_client_key(request), path, retry_after
            )
            response = Response(
                content=json.dumps({
                    "success": False,
                    "message": f"Rate limit exceeded. Please try again in {retry_after} seconds.",
                    "data": None,
                    "errors": [{"field": None, "message": f"Rate limit exceeded. Please try again in {retry_after} seconds."}],
                }),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        # Wrap send to add rate limit headers
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", str(settings.API_RATE_LIMIT_PER_MINUTE).encode()))
                headers.append((b"x-ratelimit-remaining", str(max(0, remaining)).encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def get_rate_limiter() -> RateLimiter:
    return rate_limiter