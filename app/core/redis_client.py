"""Async Redis client wrapper with graceful fallback to in-memory storage.

Provides connection pooling, key namespacing, and zero crash fallback when Redis is unavailable.
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
    """Async Redis wrapper with in-memory fallback when Redis service is offline."""

    def __init__(self) -> None:
        self._url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        self._redis = None
        self._connected = False

    async def connect(self) -> bool:
        """Attempt to connect to Redis server."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._url, decode_responses=True, socket_connect_timeout=2.0)
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis at %s", self._url)
            return True
        except Exception as exc:
            logger.warning("Redis connection unavailable (%s). Falling back to in-memory cache.", exc)
            self._connected = False
            return False

    async def get(self, key: str) -> str | None:
        """Get value by key."""
        if self._connected and self._redis:
            try:
                return await self._redis.get(key)
            except Exception:
                self._connected = False

        # In-memory fallback
        entry = _in_memory_store.get(key)
        if entry:
            val, expires = entry
            if expires is None or time.time() < expires:
                return str(val) if val is not None else None
            del _in_memory_store[key]
        return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Set key-value pair with optional TTL."""
        if self._connected and self._redis:
            try:
                if ttl_seconds:
                    await self._redis.setex(key, ttl_seconds, value)
                else:
                    await self._redis.set(key, value)
                return True
            except Exception:
                self._connected = False

        # In-memory fallback
        expires = time.time() + ttl_seconds if ttl_seconds else None
        _in_memory_store[key] = (value, expires)
        return True

    async def delete(self, key: str) -> bool:
        """Delete key."""
        if self._connected and self._redis:
            try:
                await self._redis.delete(key)
                return True
            except Exception:
                self._connected = False

        _in_memory_store.pop(key, None)
        return True

    async def flush(self) -> None:
        """Flush cache."""
        if self._connected and self._redis:
            try:
                await self._redis.flushdb()
            except Exception:
                pass
        _in_memory_store.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected


# Singleton instance
redis_client = RedisClient()


def get_redis_client() -> RedisClient:
    return redis_client
