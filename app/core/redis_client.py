"""Async Redis client wrapper with production-safe configuration.

Provides connection pooling, key namespacing, token blocklist, distributed locking,
and in-memory fallback ONLY for local development.
In production/staging, Redis is REQUIRED and connection failures will raise exceptions.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import logging
import time
from typing import Any, AsyncIterator
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_in_memory_store: dict[str, tuple[Any, float | None]] = {}
_in_memory_locks: dict[str, asyncio.Lock] = {}


def _hash_token_string(token: str) -> str:
    """Return sha256 hash for secure key indexing in Redis."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RedisClient:
    """Async Redis wrapper with token revocation, locking, and in-memory fallback."""

    def __init__(self) -> None:
        raw_url = getattr(settings, "REDIS_URL", "")
        if not raw_url:
            if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
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

    # ---------------------------------------------------------------------------
    # Token Blocklist & Stateless Invalidation Engine
    # ---------------------------------------------------------------------------

    async def blacklist_token(self, token: str, ttl_seconds: int) -> bool:
        """Store access token hash in blocklist with TTL matching expiration."""
        if not token or ttl_seconds <= 0:
            return False
        token_hash = _hash_token_string(token)
        key = f"blacklist:token:{token_hash}"
        return await self.set(key, "1", ttl_seconds=int(ttl_seconds))

    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if access token is in blocklist."""
        if not token:
            return False
        token_hash = _hash_token_string(token)
        key = f"blacklist:token:{token_hash}"
        val = await self.get(key)
        return val is not None

    async def revoke_user_tokens(self, user_id: str | uuid.UUID, ttl_seconds: int = 86400) -> bool:
        """Invalidate all access tokens issued to this user prior to current timestamp."""
        if not user_id:
            return False
        key = f"revoked_before:user:{str(user_id)}"
        cutoff_timestamp = str(int(time.time()))
        return await self.set(key, cutoff_timestamp, ttl_seconds=ttl_seconds)

    async def get_user_revoked_before(self, user_id: str | uuid.UUID) -> int | None:
        """Get the UNIX timestamp prior to which all user tokens are invalid."""
        if not user_id:
            return None
        key = f"revoked_before:user:{str(user_id)}"
        val = await self.get(key)
        if val is not None:
            try:
                return int(val)
            except ValueError:
                return None
        return None

    # ---------------------------------------------------------------------------
    # Distributed Locking Mechanism
    # ---------------------------------------------------------------------------

    @asynccontextmanager
    async def lock(self, lock_key: str, ttl_seconds: int = 10) -> AsyncIterator[bool]:
        """Distributed mutex lock for atomic operations (e.g. refresh token rotation)."""
        prefixed_key = f"lock:{lock_key}"
        lock_val = str(uuid.uuid4())
        acquired = False

        if self._connected and self._redis:
            try:
                # Redis SET NX EX distributed lock
                res = await self._redis.set(prefixed_key, lock_val, nx=True, ex=ttl_seconds)
                acquired = bool(res)
                if not acquired:
                    # Retry with small backoff
                    for _ in range(10):
                        await asyncio.sleep(0.1)
                        res = await self._redis.set(prefixed_key, lock_val, nx=True, ex=ttl_seconds)
                        if res:
                            acquired = True
                            break
            except Exception as exc:
                logger.warning("Redis lock failed, falling back to local lock: %s", exc)
                acquired = False

        if not acquired and not self._is_production:
            # Fallback to in-memory lock for local development
            if prefixed_key not in _in_memory_locks:
                _in_memory_locks[prefixed_key] = asyncio.Lock()
            local_lock = _in_memory_locks[prefixed_key]
            await local_lock.acquire()
            acquired = True
            try:
                yield acquired
            finally:
                if local_lock.locked():
                    local_lock.release()
            return

        try:
            yield acquired
        finally:
            if acquired and self._connected and self._redis:
                try:
                    # Release lock if value matches
                    curr_val = await self._redis.get(prefixed_key)
                    if curr_val == lock_val:
                        await self._redis.delete(prefixed_key)
                except Exception as exc:
                    logger.debug("Failed releasing redis lock %s: %s", prefixed_key, exc)

    @property
    def is_connected(self) -> bool:
        return self._connected


# Singleton instance
redis_client = RedisClient()


def get_redis_client() -> RedisClient:
    return redis_client