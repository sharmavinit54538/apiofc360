"""Utility functions for payroll calculations and exports."""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Any


def calculate_gross_and_net(
    basic: float,
    hra: float,
    allowances: float,
    deductions: float,
) -> tuple[float, float]:
    """Calculate gross earnings and net pay."""
    gross = round(basic + hra + allowances, 2)
    net = round(gross - deductions, 2)
    return gross, max(0.0, net)


def generate_csv_export(items: list[dict], headers: list[str]) -> str:
    """Generate CSV string from dictionary items."""
    output = io.StringIO()
    output.write(",".join(headers) + "\n")
    for item in items:
        row = [str(item.get(h, "")) for h in headers]
        output.write(",".join(row) + "\n")
    return output.getvalue()
