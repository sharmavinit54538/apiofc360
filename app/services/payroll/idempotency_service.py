"""Idempotency management for financial and state-mutating payroll operations."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from fastapi import HTTPException, Header, status

from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class IdempotencyService:
    """Handles idempotency checking, locking, and result caching."""

    PREFIX = "payroll:idempotency:"

    @classmethod
    async def get_cached_result(cls, key: str) -> Optional[dict[str, Any]]:
        """Retrieve previously cached response for an idempotency key."""
        if not key:
            return None
        cache_key = f"{cls.PREFIX}{key}"
        try:
            cached_val = await redis_client.get(cache_key)
            if cached_val:
                data = json.loads(cached_val)
                if data.get("status") == "IN_PROGRESS":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A request with this Idempotency-Key is currently being processed. Please retry shortly.",
                    )
                return data
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Error reading idempotency key %s: %s", key, e)
        return None

    @classmethod
    async def lock_key(cls, key: str, ttl_seconds: int = 60) -> None:
        """Lock key to prevent concurrent duplicate executions."""
        if not key:
            return
        cache_key = f"{cls.PREFIX}{key}"
        payload = json.dumps({"status": "IN_PROGRESS"})
        try:
            await redis_client.set(cache_key, payload, ttl_seconds=ttl_seconds)
        except Exception as e:
            logger.warning("Error locking idempotency key %s: %s", key, e)

    @classmethod
    async def store_result(
        cls, key: str, status_code: int, response_data: Any, ttl_seconds: int = 86400
    ) -> None:
        """Store completed response under the idempotency key for 24 hours."""
        if not key:
            return
        cache_key = f"{cls.PREFIX}{key}"
        payload = json.dumps({
            "status": "COMPLETED",
            "status_code": status_code,
            "data": response_data,
        })
        try:
            await redis_client.set(cache_key, payload, ttl_seconds=ttl_seconds)
        except Exception as e:
            logger.warning("Error saving idempotency result for key %s: %s", key, e)


async def require_idempotency_key(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> str:
    """Dependency for endpoints where Idempotency-Key is mandatory."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'Idempotency-Key' is required for this operation.",
        )
    return idempotency_key.strip()


async def get_optional_idempotency_key(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> Optional[str]:
    """Dependency for endpoints where Idempotency-Key is optional."""
    if idempotency_key and idempotency_key.strip():
        return idempotency_key.strip()
    return None
