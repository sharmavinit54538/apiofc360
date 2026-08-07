"""Date, Decimal, and Money formatting helper functions."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_uuid_str(val: Any) -> Optional[str]:
    """Safely convert UUID or object to string."""
    if val is None:
        return None
    return str(val)


def safe_isoformat(val: Any) -> Optional[str]:
    """Safely format date or datetime to ISO 8601 string."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


def get_current_date() -> date:
    """Return current UTC date."""
    return date.today()


def get_current_iso_now() -> str:
    """Return current UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()
