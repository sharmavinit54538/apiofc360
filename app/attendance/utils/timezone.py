"""Timezone utilities for company-aware attendance operations.

Provides company timezone resolution with caching, and helpers for
converting between UTC and company-local time.
"""

from __future__ import annotations

import logging
import time as time_module
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.onboarding import CompanySettings

logger = logging.getLogger(__name__)

# In-process TTL cache for company timezones
# Format: {company_id: (ZoneInfo, expiry_timestamp)}
_company_tz_cache: dict[str, tuple[ZoneInfo, float]] = {}
_TZ_CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_key(company_id: str) -> str:
    """Generate cache key for company_id."""
    return str(company_id)


async def get_company_tz(db: AsyncSession, company_id: str) -> ZoneInfo:
    """Get the company's configured timezone as a ZoneInfo object.

    Uses a 5-minute in-process TTL cache. Falls back to
    ATTENDANCE_DEFAULT_TIMEZONE with a warning if the configured
    timezone is invalid or not set.

    Args:
        db: Database session
        company_id: Company UUID string

    Returns:
        ZoneInfo object for the company's timezone
    """
    cache_key = _cache_key(company_id)
    now = time_module.time()

    # Check cache
    if cache_key in _company_tz_cache:
        tz, expiry = _company_tz_cache[cache_key]
        if now < expiry:
            return tz

    # Fetch from database
    stmt = select(CompanySettings.timezone).where(CompanySettings.company_id == company_id)
    result = await db.execute(stmt)
    tz_str = result.scalar_one_or_none()

    if not tz_str:
        logger.warning(
            "Company %s has no timezone configured, using default %s",
            company_id,
            settings.ATTENDANCE_DEFAULT_TIMEZONE,
        )
        tz = ZoneInfo(settings.ATTENDANCE_DEFAULT_TIMEZONE)
    else:
        try:
            tz = ZoneInfo(tz_str.strip())
        except ZoneInfoNotFoundError:
            logger.warning(
                "Company %s has invalid timezone '%s', using default %s",
                company_id,
                tz_str,
                settings.ATTENDANCE_DEFAULT_TIMEZONE,
            )
            tz = ZoneInfo(settings.ATTENDANCE_DEFAULT_TIMEZONE)

    # Cache with TTL
    _company_tz_cache[cache_key] = (tz, now + _TZ_CACHE_TTL_SECONDS)
    return tz


def invalidate_company_tz(company_id: str) -> None:
    """Invalidate the cached timezone for a company.

    Call this whenever company timezone settings are updated.

    Args:
        company_id: Company UUID string
    """
    cache_key = _cache_key(company_id)
    _company_tz_cache.pop(cache_key, None)


def now_utc() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def to_company_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    """Convert a UTC datetime to company local time.

    Args:
        dt_utc: Timezone-aware UTC datetime
        tz: Company timezone

    Returns:
        Timezone-aware datetime in company timezone
    """
    if dt_utc.tzinfo is None:
        # Assume UTC if naive
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(tz)


def combine_local(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Combine a date and time in company timezone to an aware datetime.

    Args:
        d: Date component
        t: Time component (naive, interpreted in company timezone)
        tz: Company timezone

    Returns:
        Timezone-aware datetime in company timezone
    """
    return datetime.combine(d, t).replace(tzinfo=tz)


def company_today(tz: ZoneInfo) -> date:
    """Get today's date in the company's timezone.

    Args:
        tz: Company timezone

    Returns:
        Date in company timezone
    """
    return now_utc().astimezone(tz).date()


def shift_start_datetime(business_date: date, start_time: time, tz: ZoneInfo) -> datetime:
    """Get shift start as aware datetime in company timezone.

    Args:
        business_date: The business date (date of shift start)
        start_time: Shift start time (naive)
        tz: Company timezone

    Returns:
        Timezone-aware shift start datetime
    """
    return combine_local(business_date, start_time, tz)


def shift_end_datetime(
    business_date: date, start_time: time, end_time: time, is_overnight: bool, tz: ZoneInfo
) -> datetime:
    """Get shift end as aware datetime in company timezone.

    Args:
        business_date: The business date (date of shift start)
        start_time: Shift start time (naive)
        end_time: Shift end time (naive)
        is_overnight: Whether shift crosses midnight
        tz: Company timezone

    Returns:
        Timezone-aware shift end datetime
    """
    if is_overnight:
        return combine_local(business_date + timedelta(days=1), end_time, tz)
    return combine_local(business_date, end_time, tz)


def checkin_window_start(
    shift_start: datetime, early_window_mins: int
) -> datetime:
    """Get the earliest allowed check-in time (shift start - early window).

    Args:
        shift_start: Shift start datetime (aware)
        early_window_mins: Minutes before shift start to allow check-in

    Returns:
        Earliest allowed check-in datetime (aware)
    """
    return shift_start - timedelta(minutes=early_window_mins)


def checkout_window_end(
    shift_end: datetime, post_shift_window_mins: int
) -> datetime:
    """Get the latest allowed check-out time (shift end + post window).

    Args:
        shift_end: Shift end datetime (aware)
        post_shift_window_mins: Minutes after shift end to allow check-out

    Returns:
        Latest allowed check-out datetime (aware)
    """
    return shift_end + timedelta(minutes=post_shift_window_mins)


def is_time_in_window(check_time: datetime, window_start: datetime, window_end: datetime) -> bool:
    """Check if a time falls within a window [window_start, window_end].

    Args:
        check_time: Time to check (aware)
        window_start: Window start (aware)
        window_end: Window end (aware)

    Returns:
        True if check_time is within window (inclusive)
    """
    return window_start <= check_time <= window_end