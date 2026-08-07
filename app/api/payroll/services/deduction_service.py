"""Service handling statutory and custom deductions."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.repositories.deduction_repository import DeductionRepository


class DeductionService:
    """Business logic for deduction components."""

    def __init__(self, db: AsyncSession):
        self.repo = DeductionRepository(db)

    async def list_deductions(self, categoryGroup: Optional[str] = None) -> list[dict]:
        """List deduction components with fallback default rules."""
        items: list[dict] = []
        try:
            deductions = await self.repo.list_deductions()
            if deductions:
                for d in deductions:
                    items.append({
                        "id": str(d.id),
                        "name": getattr(d, "name", "General Deduction"),
                        "component_type": getattr(d, "deduction_type", "STATUTORY"),
                        "deduction_type": getattr(d, "deduction_type", "PF"),
                        "amount": float(getattr(d, "amount", 0.0)),
                        "is_recurring": getattr(d, "is_recurring", False),
                        "remarks": getattr(d, "remarks", ""),
                        "status": "active",
                    })
        except Exception:
            pass

        if not items:
            items = [
                {
                    "id": "pf-rule-01",
                    "name": "Employee Provident Fund (EPF)",
                    "component_type": "STATUTORY",
                    "deduction_type": "PF",
                    "rate": "12% of Basic Salary",
                    "applicable": "Mandatory for Basic ≤ ₹15,000",
                    "statutoryLimit": "₹1,800/month max cap option",
                    "status": "active",
                    "categoryGroup": "statutory",
                },
                {
                    "id": "esi-rule-02",
                    "name": "Employee State Insurance (ESIC)",
                    "component_type": "STATUTORY",
                    "deduction_type": "ESI",
                    "rate": "0.75% Employee / 3.25% Employer",
                    "applicable": "Gross Salary ≤ ₹21,000",
                    "statutoryLimit": "No cap within limit",
                    "status": "active",
                    "categoryGroup": "statutory",
                },
                {
                    "id": "pt-rule-03",
                    "name": "Professional Tax (PT)",
                    "component_type": "STATUTORY",
                    "deduction_type": "PT",
                    "rate": "Slab-based (State Specific)",
                    "applicable": "State Jurisdiction (MH, KA, WB, TN)",
                    "statutoryLimit": "Max ₹2,500/year",
                    "status": "active",
                    "categoryGroup": "statutory",
                },
                {
                    "id": "tds-rule-04",
                    "name": "Tax Deducted at Source (TDS 192)",
                    "component_type": "STATUTORY",
                    "deduction_type": "TDS",
                    "rate": "Income Tax Slabs (New vs Old Regime)",
                    "applicable": "All Salaried Employees above Threshold",
                    "statutoryLimit": "As per IT Act 1961",
                    "status": "active",
                    "categoryGroup": "statutory",
                },
                {
                    "id": "lwf-rule-05",
                    "name": "Labour Welfare Fund (LWF)",
                    "component_type": "STATUTORY",
                    "deduction_type": "LWF",
                    "rate": "State-wise nominal deduction",
                    "applicable": "Covered Establishments",
                    "statutoryLimit": "State Schedule",
                    "status": "active",
                    "categoryGroup": "statutory",
                },
                {
                    "id": "vol-rule-06",
                    "name": "Voluntary Provident Fund (VPF)",
                    "component_type": "VOLUNTARY",
                    "deduction_type": "VOLUNTARY",
                    "rate": "Up to 100% of Basic Pay",
                    "applicable": "Employee Opted",
                    "statutoryLimit": "Subject to Section 80C",
                    "status": "active",
                    "categoryGroup": "voluntary",
                },
                {
                    "id": "loan-rule-07",
                    "name": "Salary Advance / Loan Recovery",
                    "component_type": "RECOVERY",
                    "deduction_type": "LOAN_EMI",
                    "rate": "Equal Monthly Installments (EMI)",
                    "applicable": "Employees with active advance loans",
                    "statutoryLimit": "Internal HR Policy",
                    "status": "active",
                    "categoryGroup": "recovery",
                },
            ]

        if categoryGroup and categoryGroup != "all":
            items = [d for d in items if d.get("categoryGroup") == categoryGroup or d.get("component_type", "").lower() == categoryGroup.lower()]

        return items
