"""Async Redis client wrapper with production-safe configuration.

Provides connection pooling, key namespacing, and in-memory fallback ONLY for local development.
In production/staging, Redis is REQUIRED and connection failures will raise exceptions.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_in_memory_store: dict[str, tuple[Any, float | None]] = {}


class RedisClient:
    """Async Redis wrapper with in-memory fallback for local development only."""

    def __init__(self) -> None:
        # Use explicit REDIS_URL from settings, or local default for dev
        raw_url = getattr(settings, "REDIS_URL", "")
        if not raw_url:
            if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
                # This should never happen due to config validation, but safety check
                raise ValueError("REDIS_URL must be configured in production")
            raw_url = "redis://localhost:6379/0"
        self._url = raw_url
        self._redis = None
        self._connected = False
        self._is_production = settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}

    async def connect(self) -> bool:
        """Attempt to connect to Redis server. Required in production."""
        try:
            import redis.asyncio as aioredis  # type: ignore
            self._redis = aioredis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_timeout=5.0,
                max_connections=50,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis at %s", self._url)
            return True
        except Exception as exc:
            self._connected = False
            if self._is_production:
                logger.critical("Redis connection REQUIRED in production but unavailable: %s", exc)
                raise RuntimeError(f"Redis connection required in production: {exc}") from exc
            logger.warning("Redis connection unavailable (%s). Falling back to in-memory cache (local only).", exc)
            return False

    async def get(self, key: str) -> str | None:
        """Get value by key. Requires Redis in production."""
        if self._connected and self._redis:
            try:
                return await self._redis.get(key)
            except Exception as exc:
                self._connected = False
                if self._is_production:
                    logger.error("Redis GET failed in production: %s", exc)
                    raise

        if self._is_production:
            raise RuntimeError("Redis required in production but not connected")

        # In-memory fallback (local development only)
        entry = _in_memory_store.get(key)
        if entry:
            val, expires = entry
            if expires is None or time.time() < expires:
                return str(val) if val is not None else None
            del _in_memory_store[key]
        return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Set key-value pair with optional TTL. Requires Redis in production."""
        if self._connected and self._redis:
            try:
                if ttl_seconds:
                    await self._redis.setex(key, ttl_seconds, value)
                else:
                    await self._redis.set(key, value)
                return True
            except Exception as exc:
                self._connected = False
                if self._is_production:
                    logger.error("Redis SET failed in production: %s", exc)
                    raise

        if self._is_production:
            raise RuntimeError("Redis required in production but not connected")

        # In-memory fallback (local development only)
        expires = time.time() + ttl_seconds if ttl_seconds else None
        _in_memory_store[key] = (value, expires)
        return True

    async def delete(self, key: str) -> bool:
        """Delete key. Requires Redis in production."""
        if self._connected and self._redis:
            try:
                await self._redis.delete(key)
                return True
            except Exception as exc:
                self._connected = False
                if self._is_production:
                    logger.error("Redis DELETE failed in production: %s", exc)
                    raise

        if self._is_production:
            raise RuntimeError("Redis required in production but not connected")

        _in_memory_store.pop(key, None)
        return True

    async def flush(self) -> None:
        """Flush cache."""
        if self._connected and self._redis:
            try:
                await self._redis.flushdb()
            except Exception as exc:
                if self._is_production:
                    logger.error("Redis FLUSH failed in production: %s", exc)
                    raise
        _in_memory_store.clear()

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        if not self._connected or not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected


# Singleton instance
redis_client = RedisClient()


def get_redis_client() -> RedisClient:
    return redis_client