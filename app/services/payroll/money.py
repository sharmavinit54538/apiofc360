"""Integer-paise and statutory rounding primitives.

All payroll arithmetic crosses the API boundary as integer paise. Statutory
contributions may use a configured whole-rupee boundary; Net Pay remains exact
integer paise. Never use binary floating-point ``round`` for money.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

PAISE_PER_RUPEE = 100
MONEY_CONTEXT_PRECISION = 34


def as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid monetary value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("Monetary values must be finite")
    return result


def allocate_annual_paise(annual_paise: int) -> tuple[int, ...]:
    """Allocate an annual amount across 12 months without losing remainders.

    The first ``remainder`` months receive one extra paise. The result always
    sums exactly to the annual amount and is stable for historical periods.
    """
    if isinstance(annual_paise, bool) or not isinstance(annual_paise, int):
        raise TypeError("Annual compensation must be an integer number of paise")
    if annual_paise < 0:
        raise ValueError("Annual compensation cannot be negative")
    base, remainder = divmod(annual_paise, 12)
    return tuple(base + (month < remainder) for month in range(12))


def assert_payroll_reconciles(gross_paise: int, deductions_paise: int, net_paise: int) -> None:
    """Reject any unexplained difference in posted payroll amounts."""
    if gross_paise - deductions_paise != net_paise:
        raise ValueError(
            "Payroll financial integrity violation: gross minus deductions "
            "does not equal net pay"
        )


def round_paise(value: Any) -> int:
    """Round an amount to the nearest paise, half up."""
    with localcontext() as context:
        context.prec = MONEY_CONTEXT_PRECISION
        return int(as_decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_to_rupee_paise(value: Any) -> int:
    """Return a multiple of 100 using statutory ROUND_HALF_UP semantics."""
    paise = as_decimal(value)
    return int((paise / PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP) * PAISE_PER_RUPEE)


def round_up_to_rupee_paise(value: Any) -> int:
    """Round a statutory amount up to the next whole rupee in integer paise.

    For an already integral rupee amount this leaves the amount unchanged;
    any positive fractional rupee advances to the next rupee.
    """
    paise = as_decimal(value)
    with localcontext() as context:
        context.prec = MONEY_CONTEXT_PRECISION
        return int((paise / PAISE_PER_RUPEE).to_integral_value(rounding=ROUND_CEILING) * PAISE_PER_RUPEE)


def rupees_to_paise(value: Any) -> int:
    """Convert a legacy rupee amount without going through float arithmetic."""
    return round_paise(as_decimal(value) * PAISE_PER_RUPEE)


def paise_to_rupees(value: Any) -> Decimal:
    return (as_decimal(value) / PAISE_PER_RUPEE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Explicit name used in payroll design documents and external integrations.
ROUND_HALF_UP_TO_RUPEE = round_to_rupee_paise
