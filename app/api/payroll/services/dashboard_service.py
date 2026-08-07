"""Service handling dashboard overview metrics and hero statistics."""
from __future__ import annotations

from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.repositories.payroll_repository import PayrollRepository


class DashboardService:
    """Business logic for high-level payroll hero metrics and summary widgets."""

    def __init__(self, db: AsyncSession):
        self.repo = PayrollRepository(db)

    async def get_hero_card_metrics(self, month: Optional[int], year: Optional[int]) -> dict:
        """Fetch hero card summary metrics."""
        today = date.today()
        m = month or today.month
        y = year or today.year

        metrics = await self.repo.get_hero_metrics(m, y)
        total_emp = metrics["total_employees"]
        processed = metrics["processed_count"]

        status = "COMPLETED" if (processed == total_emp and total_emp > 0) else ("IN_PROGRESS" if processed > 0 else "NOT_STARTED")

        return {
            "cycle_month": f"{y}-{m:02d}",
            "total_employees": total_emp,
            "total_gross": round(metrics["total_gross"], 2),
            "total_deductions": round(metrics["total_deductions"], 2),
            "total_net": round(metrics["total_net"], 2),
            "processed_count": processed,
            "paid_count": metrics["paid_count"],
            "pending_count": total_emp - processed,
            "status": status,
        }
