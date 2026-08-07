"""Validation helper functions for Payroll module."""
from __future__ import annotations

import uuid
from typing import Optional
from app.api.payroll.exceptions import BadRequestException


def validate_month_year(month: Optional[int], year: Optional[int]) -> tuple[int, int]:
    """Validate and normalize month and year parameters."""
    if month is not None and not (1 <= month <= 12):
        raise BadRequestException("Month must be between 1 and 12.")
    if year is not None and not (2000 <= year <= 2100):
        raise BadRequestException("Year must be a valid 4-digit year.")
    return month, year


def validate_uuid(val: str, name: str = "ID") -> uuid.UUID:
    """Validate string as UUID."""
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError):
        raise BadRequestException(f"Invalid {name} format.")
