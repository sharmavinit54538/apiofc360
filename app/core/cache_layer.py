"""Redis cache layer for slow-changing data with tenant-scoped keys and invalidation."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from app.core.cache import (
    async_cache_get,
    async_cache_set,
    cache_delete,
    get_resource_version,
    increment_resource_version,
    make_cache_key,
)
from app.core.redis_client import get_redis_client


# Cache TTLs for different resource types (in seconds)
CACHE_TTLS = {
    "company_settings": 300,      # 5 min
    "work_schedule": 300,         # 5 min
    "timezone": 3600,             # 1 hour
    "sidebar_permissions": 600,   # 10 min
    "departments": 300,           # 5 min
    "shifts": 120,                # 2 min
    "shifts_options": 120,        # 2 min
    "holidays": 600,              # 10 min
    "employee_by_user": 60,       # 1 min
    "role_permissions": 600,      # 10 min
}


async def get_cached_company_settings(company_id: str, loader: Callable) -> Any:
    """Get company settings with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "company_settings"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["company_settings"],
        company_id=company_id,
        resource="company_settings",
    )


async def get_cached_work_schedule(company_id: str, loader: Callable) -> Any:
    """Get work schedule with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "work_schedule"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["work_schedule"],
        company_id=company_id,
        resource="work_schedule",
    )


async def get_cached_timezone(company_id: str, loader: Callable) -> Any:
    """Get timezone with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "timezone"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["timezone"],
        company_id=company_id,
        resource="timezone",
    )


async def get_cached_sidebar_permissions(company_id: str, role: str, loader: Callable) -> Any:
    """Get sidebar permissions for a role with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, f"sidebar_permissions:{role}"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["sidebar_permissions"],
        company_id=company_id,
        resource="sidebar_permissions",
    )


async def get_cached_departments(company_id: str, loader: Callable) -> Any:
    """Get departments with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "departments"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["departments"],
        company_id=company_id,
        resource="departments",
    )


async def get_cached_shifts(company_id: str, loader: Callable) -> Any:
    """Get shifts with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "shifts"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["shifts"],
        company_id=company_id,
        resource="shifts",
    )


async def get_cached_shifts_options(company_id: str, loader: Callable) -> Any:
    """Get shift options with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, "shifts_options"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["shifts_options"],
        company_id=company_id,
        resource="shifts_options",
    )


async def get_cached_holidays(company_id: str, year: int | None, loader: Callable) -> Any:
    """Get holidays with caching."""
    key_suffix = f"holidays:{year}" if year else "holidays"
    return await cached_get_or_set(
        key=make_cache_key(company_id, key_suffix),
        loader=loader,
        ttl_seconds=CACHE_TTLS["holidays"],
        company_id=company_id,
        resource="holidays",
    )


async def get_cached_employee_by_user(user_id: str, loader: Callable) -> Any:
    """Get employee by user_id with caching."""
    return await cached_get_or_set(
        key=make_cache_key(None, f"employee_by_user:{user_id}"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["employee_by_user"],
        company_id=None,
        resource="employee_by_user",
    )


async def get_cached_role_permissions(company_id: str, role: str, loader: Callable) -> Any:
    """Get role permissions with caching."""
    return await cached_get_or_set(
        key=make_cache_key(company_id, f"role_permissions:{role}"),
        loader=loader,
        ttl_seconds=CACHE_TTLS["role_permissions"],
        company_id=company_id,
        resource="role_permissions",
    )


# Invalidation functions - call these on create/update/delete operations

async def invalidate_company_settings_cache(company_id: str) -> None:
    """Invalidate company settings cache."""
    await increment_resource_version(company_id, "company_settings")


async def invalidate_work_schedule_cache(company_id: str) -> None:
    """Invalidate work schedule cache."""
    await increment_resource_version(company_id, "work_schedule")


async def invalidate_timezone_cache(company_id: str) -> None:
    """Invalidate timezone cache."""
    await increment_resource_version(company_id, "timezone")


async def invalidate_sidebar_permissions_cache(company_id: str, role: str | None = None) -> None:
    """Invalidate sidebar permissions cache."""
    if role:
        # For role-specific, we'd need a more granular approach
        # For now, invalidate all
        pass
    await increment_resource_version(company_id, "sidebar_permissions")


async def invalidate_departments_cache(company_id: str) -> None:
    """Invalidate departments cache."""
    await increment_resource_version(company_id, "departments")


async def invalidate_shifts_cache(company_id: str) -> None:
    """Invalidate shifts cache."""
    await increment_resource_version(company_id, "shifts")
    await increment_resource_version(company_id, "shifts_options")


async def invalidate_holidays_cache(company_id: str) -> None:
    """Invalidate holidays cache."""
    await increment_resource_version(company_id, "holidays")


async def invalidate_employee_by_user_cache(user_id: str) -> None:
    """Invalidate employee by user cache."""
    await increment_resource_version(None, "employee_by_user")


async def invalidate_role_permissions_cache(company_id: str, role: str | None = None) -> None:
    """Invalidate role permissions cache."""
    await increment_resource_version(company_id, "role_permissions")


# Helper to get all cache keys for a resource (for debugging/monitoring)
async def get_cache_stats() -> dict:
    """Get cache statistics for monitoring."""
    redis = get_redis_client()
    stats = {
        "version_keys": {},
        "total_keys": 0,
    }
    try:
        if redis._redis:
            # Count version keys
            for resource in CACHE_TTLS:
                pattern = f"cache:ver:*"
                count = 0
                async for _ in redis._redis.scan_iter(match=pattern):
                    count += 1
                stats["version_keys"][resource] = count
            
            # Total keys
            stats["total_keys"] = await redis._redis.dbsize()
    except Exception:
        pass
    return stats