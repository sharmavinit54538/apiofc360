"""Per-provider rate limiter with sliding window.

Uses in-memory tracking (Redis-backed in Phase 6).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter per provider.

    Thread-safe for async usage within a single process.
    """

    def __init__(self) -> None:
        # provider_name -> list of request timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check_and_consume(
        self,
        provider: str,
        limit_rpm: int = 60,
    ) -> bool:
        """Check if a request is allowed under the rate limit.

        Returns True if allowed (and consumes a slot), False if rate limited.
        """
        now = time.monotonic()
        window_start = now - 60.0  # 1-minute window

        async with self._lock:
            # Prune expired entries
            timestamps = self._windows[provider]
            self._windows[provider] = [t for t in timestamps if t > window_start]

            if len(self._windows[provider]) >= limit_rpm:
                logger.warning(
                    "Rate limit exceeded for provider '%s': %d/%d RPM",
                    provider, len(self._windows[provider]), limit_rpm,
                )
                return False

            self._windows[provider].append(now)
            return True

    async def wait_if_needed(
        self,
        provider: str,
        limit_rpm: int = 60,
        max_wait: float = 30.0,
    ) -> bool:
        """Wait until a request slot is available, or give up after max_wait seconds.

        Returns True if a slot became available, False if timed out.
        """
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            if await self.check_and_consume(provider, limit_rpm):
                return True
            await asyncio.sleep(0.5)

        return False

    def get_usage(self, provider: str) -> dict:
        """Get current rate limit usage for a provider."""
        now = time.monotonic()
        window_start = now - 60.0
        timestamps = self._windows.get(provider, [])
        active = [t for t in timestamps if t > window_start]
        return {
            "provider": provider,
            "requests_in_window": len(active),
            "window_seconds": 60,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_limiter: SlidingWindowRateLimiter | None = None


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the global rate limiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowRateLimiter()
    return _limiter
