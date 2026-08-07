"""Cache service — hybrid TTL cache supporting synchronous in-memory and async Redis storage."""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.redis_client import get_redis_client

_store: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any | None:
    """Return cached value if not expired (sync in-memory)."""
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _store.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: float = 60.0) -> None:
    """Store value with TTL in memory."""
    _store[key] = (time.monotonic() + ttl_seconds, value)


def cache_delete(key: str) -> None:
    """Remove cache entry."""
    _store.pop(key, None)


def cache_clear() -> None:
    """Clear all cache entries."""
    _store.clear()


async def async_cache_get(key: str) -> Any | None:
    """Async cache read (Redis with in-memory fallback)."""
    redis = get_redis_client()
    raw = await redis.get(key)
    if raw is not None:
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return cache_get(key)


async def async_cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """Async cache write (Redis with in-memory fallback)."""
    redis = get_redis_client()
    try:
        val_str = json.dumps(value) if not isinstance(value, str) else value
        await redis.set(key, val_str, ttl_seconds=ttl_seconds)
    except Exception:
        pass
    cache_set(key, value, ttl_seconds=float(ttl_seconds))
