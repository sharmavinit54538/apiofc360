"""Cache service — hybrid TTL cache supporting synchronous in-memory and async Redis storage with ETag support."""

from __future__ import annotations

import hashlib
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


def generate_etag(data: Any) -> str:
    """Generate ETag from data using SHA256."""
    if isinstance(data, (dict, list)):
        content = json.dumps(data, sort_keys=True, default=str)
    else:
        content = str(data)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def check_etag(etag_header: str | None, current_etag: str) -> bool:
    """Check if ETag matches. Returns True if client has current version."""
    if not etag_header:
        return False
    # Remove quotes if present
    client_etag = etag_header.strip('"')
    return client_etag == current_etag


# Version keys for tenant-scoped cache invalidation
VERSION_KEY_PREFIX = "cache:ver"


def get_version_key(company_id: str | None, resource: str) -> str:
    """Get version key for a company+resource combination."""
    if company_id:
        return f"{VERSION_KEY_PREFIX}:{company_id}:{resource}"
    return f"{VERSION_KEY_PREFIX}:global:{resource}"


async def get_resource_version(company_id: str | None, resource: str) -> int:
    """Get current version for a resource."""
    redis = get_redis_client()
    key = get_version_key(company_id, resource)
    val = await redis.get(key)
    if val:
        try:
            return int(val)
        except Exception:
            pass
    return 0


async def increment_resource_version(company_id: str | None, resource: str) -> int:
    """Increment version for a resource (invalidates all cached entries)."""
    redis = get_redis_client()
    key = get_version_key(company_id, resource)
    try:
        # Use INCR for atomic increment
        return await redis._redis.incr(key) if redis._redis else 1
    except Exception:
        return 1


def make_cache_key(company_id: str | None, resource: str, params: dict | None = None) -> str:
    """Create a tenant-scoped cache key."""
    parts = [resource]
    if company_id:
        parts.insert(0, company_id)
    if params:
        # Sort params for consistent keys
        param_str = json.dumps(params, sort_keys=True, default=str)
        parts.append(hashlib.md5(param_str.encode()).hexdigest()[:8])
    return ":".join(parts)


async def cached_get_or_set(
    key: str,
    loader,
    ttl_seconds: int = 300,
    company_id: str | None = None,
    resource: str | None = None,
) -> Any:
    """
    Get from cache or load and cache with version-based invalidation.
    
    If resource is provided, cache key includes resource version for automatic
    invalidation when version is incremented.
    """
    # Build version-aware key
    if resource:
        version = await get_resource_version(company_id, resource)
        versioned_key = f"{key}:v{version}"
    else:
        versioned_key = key

    # Try cache
    cached = await async_cache_get(versioned_key)
    if cached is not None:
        return cached

    # Load fresh data
    data = await loader()

    # Cache it
    await async_cache_set(versioned_key, data, ttl_seconds)
    return data