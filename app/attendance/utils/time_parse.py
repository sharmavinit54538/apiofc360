"""Time parsing utilities for shift engine.

Provides strict time parsing that never silently falls back to defaults.
All shift/attendance code must use parse_time_str() for time string parsing.
"""

from __future__ import annotations

import re
from datetime import time
from typing import Union


class InvalidTimeFormatError(ValueError):
    """Raised when a time string cannot be parsed."""

    pass


# Pre-compiled regex patterns for common time formats
_TIME_24H = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_TIME_12H = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", re.IGNORECASE)
_TIME_12H_NO_MIN = re.compile(r"^(\d{1,2})\s*(AM|PM)$", re.IGNORECASE)


def parse_time_str(value: Union[str, time, None]) -> time:
    """Parse a time string into a datetime.time object.

    Accepted formats:
    - "HH:MM" (24-hour, e.g., "09:00", "22:30")
    - "HH:MM:SS" (24-hour with seconds, e.g., "09:00:00")
    - "H:MM" (24-hour, e.g., "9:00")
    - "HH:MM AM/PM" (12-hour, e.g., "9:00 AM", "09:00 PM")
    - "H:MM AM/PM" (12-hour, e.g., "9 AM", "11 PM")
    - "H AM/PM" (12-hour no minutes, e.g., "9 AM", "6 PM")
    - datetime.time objects (passed through unchanged)

    Args:
        value: Time string, time object, or None

    Returns:
        datetime.time object

    Raises:
        InvalidTimeFormatError: If the input cannot be parsed
    """
    if isinstance(value, time):
        return value

    if value is None:
        raise InvalidTimeFormatError("Time value is None")

    if not isinstance(value, str):
        raise InvalidTimeFormatError(f"Expected string or time, got {type(value).__name__}")

    clean = value.strip()
    if not clean:
        raise InvalidTimeFormatError("Time string is empty")

    # Try 24-hour formats first (HH:MM, HH:MM:SS, H:MM)
    match = _TIME_24H.match(clean)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3)) if match.group(3) else 0

        if not (0 <= hour <= 23):
            raise InvalidTimeFormatError(f"Hour {hour} out of range (0-23)")
        if not (0 <= minute <= 59):
            raise InvalidTimeFormatError(f"Minute {minute} out of range (0-59)")
        if not (0 <= second <= 59):
            raise InvalidTimeFormatError(f"Second {second} out of range (0-59)")

        return time(hour, minute, second)

    # Try 12-hour format with minutes (HH:MM AM/PM)
    match = _TIME_12H.match(clean)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3).upper()

        if not (1 <= hour <= 12):
            raise InvalidTimeFormatError(f"12-hour format hour {hour} out of range (1-12)")
        if not (0 <= minute <= 59):
            raise InvalidTimeFormatError(f"Minute {minute} out of range (0-59)")

        # Convert to 24-hour
        if period == "AM":
            hour_24 = 0 if hour == 12 else hour
        else:  # PM
            hour_24 = 12 if hour == 12 else hour + 12

        return time(hour_24, minute)

    # Try 12-hour format without minutes (H AM/PM)
    match = _TIME_12H_NO_MIN.match(clean)
    if match:
        hour = int(match.group(1))
        period = match.group(2).upper()

        if not (1 <= hour <= 12):
            raise InvalidTimeFormatError(f"12-hour format hour {hour} out of range (1-12)")

        if period == "AM":
            hour_24 = 0 if hour == 12 else hour
        else:  # PM
            hour_24 = 12 if hour == 12 else hour + 12

        return time(hour_24, 0)

    raise InvalidTimeFormatError(
        f"Invalid time format: '{value}'. "
        f"Use HH:MM, HH:MM:SS, H:MM, HH:MM AM/PM, H:MM AM/PM, or H AM/PM"
    )


def format_hhmm(value: Union[time, str, None]) -> str:
    """Format a time as 'HH:MM' (24-hour, zero-padded).

    Args:
        value: time object, ISO time string, or None

    Returns:
        Formatted string like "09:00" or "22:30", empty string if None/invalid
    """
    if value is None:
        return ""

    if isinstance(value, time):
        return value.strftime("%H:%M")

    if isinstance(value, str):
        try:
            parsed = parse_time_str(value)
            return parsed.strftime("%H:%M")
        except InvalidTimeFormatError:
            return ""

    return ""