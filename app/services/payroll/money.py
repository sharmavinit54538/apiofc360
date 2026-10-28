"""Integer-paise and statutory rounding primitives.

All payroll arithmetic crosses the API boundary as integer paise.  Statutory
contributions and final Net Pay use ROUND_HALF_UP to the nearest whole rupee
(100 paise), never binary floating-point ``round``.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

PAISE_PER_RUPEE = 100


def as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_paise(value: Any) -> int:
    """Round an amount to the nearest paise, half up."""
    return int(as_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_to_rupee_paise(value: Any) -> int:
    """Return a multiple of 100 using statutory ROUND_HALF_UP semantics."""
    paise = as_decimal(value)
    return int((paise / PAISE_PER_RUPEE).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * PAISE_PER_RUPEE)


def rupees_to_paise(value: Any) -> int:
    """Convert a legacy rupee amount without going through float arithmetic."""
    return round_paise(as_decimal(value) * PAISE_PER_RUPEE)


def paise_to_rupees(value: Any) -> Decimal:
    return (as_decimal(value) / PAISE_PER_RUPEE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Explicit name used in payroll design documents and external integrations.
ROUND_HALF_UP_TO_RUPEE = round_to_rupee_paise
