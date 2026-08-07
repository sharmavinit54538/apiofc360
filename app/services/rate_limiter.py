"""In-memory sliding window rate limiter for login requests."""

import asyncio
import time
from collections import deque
import logging

from fastapi import Request, status

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class InMemorySlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[float]] = {}
        self.lock = asyncio.Lock()

    async def check_rate_limit(self, ip: str) -> None:
        """Check if request limit is exceeded for a given IP."""
        async with self.lock:
            now = time.time()
            if ip not in self.requests:
                self.requests[ip] = deque()

            timestamps = self.requests[ip]

            # Remove timestamps outside the sliding window
            while timestamps and timestamps[0] < now - self.window_seconds:
                timestamps.popleft()

            if len(timestamps) >= self.limit:
                logger.warning(
                    "Rate limit exceeded | ip=%s | limit=%d | window=%ds",
                    ip,
                    self.limit,
                    self.window_seconds,
                )
                raise AppException(
                    message="Too many login attempts. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            timestamps.append(now)


# Create global rate limiter instance using settings
login_rate_limiter = InMemorySlidingWindowRateLimiter(
    limit=settings.LOGIN_RATE_LIMIT_LIMIT,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW,
)


async def check_login_rate_limit(request: Request) -> None:
    """FastAPI dependency to rate limit login requests per IP."""
    ip = None
    if request.headers.get("x-forwarded-for"):
        ip = request.headers.get("x-forwarded-for").split(",")[0].strip()
    elif request.client:
        ip = request.client.host

    if not ip:
        ip = "unknown"

    await login_rate_limiter.check_rate_limit(ip)


# Onboarding rate limiter (e.g. max 5 requests per minute)
onboarding_rate_limiter = InMemorySlidingWindowRateLimiter(
    limit=5,
    window_seconds=60,
)


async def check_onboarding_rate_limit(request: Request) -> None:
    """FastAPI dependency to rate limit onboarding requests per IP."""
    ip = None
    if request.headers.get("x-forwarded-for"):
        ip = request.headers.get("x-forwarded-for").split(",")[0].strip()
    elif request.client:
        ip = request.client.host

    if not ip:
        ip = "unknown"

    try:
        await onboarding_rate_limiter.check_rate_limit(ip)
    except AppException as e:
        raise AppException(
            message="Too many requests. Please try again later.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        ) from e
