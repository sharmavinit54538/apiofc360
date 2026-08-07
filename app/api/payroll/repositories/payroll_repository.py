"""Database repository for PayCycle and PayrollAttendanceInput entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayCycle, PayrollAttendanceInput, Payslip


class PayrollRepository:
    """SQLAlchemy Repository for PayCycle and attendance entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_cycle_by_id(self, cycle_id: uuid.UUID) -> Optional[PayCycle]:
        """Fetch pay cycle by ID."""
        stmt = select(PayCycle).where(PayCycle.id == cycle_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_cycles(self, month: Optional[int] = None, year: Optional[int] = None) -> Sequence[PayCycle]:
        """List pay cycles filtered by month/year."""
        stmt = select(PayCycle)
        if month:
            stmt = stmt.where(PayCycle.period_month == month)
        if year:
            stmt = stmt.where(PayCycle.period_year == year)
        res = await self.db.execute(stmt.order_by(PayCycle.created_at.desc()))
        return res.scalars().all()

    async def create_cycle(self, cycle: PayCycle) -> PayCycle:
        """Create and commit a new pay cycle."""
        self.db.add(cycle)
        await self.db.commit()
        await self.db.refresh(cycle)
        return cycle

    async def get_hero_metrics(self, month: int, year: int) -> dict:
        """Retrieve aggregated hero card metrics."""
        stmt = select(
            func.count(Payslip.id).label("total_employees"),
            func.coalesce(func.sum(Payslip.gross_earnings), 0.0).label("total_gross"),
            func.coalesce(func.sum(Payslip.total_deductions), 0.0).label("total_deductions"),
            func.coalesce(func.sum(Payslip.net_pay), 0.0).label("total_net"),
            func.sum(case((Payslip.generated_at.is_not(None), 1), else_=0)).label("processed_count"),
            func.sum(case((Payslip.payment_status == "PAID", 1), else_=0)).label("paid_count"),
        ).where(Payslip.period_month == month, Payslip.period_year == year)

        res = await self.db.execute(stmt)
        row = res.first()
        if not row or not row.total_employees:
            return {
                "total_employees": 0, "total_gross": 0.0,
                "total_deductions": 0.0, "total_net": 0.0,
                "processed_count": 0, "paid_count": 0,
            }
        return {
            "total_employees": int(row.total_employees or 0),
            "total_gross": float(row.total_gross or 0.0),
            "total_deductions": float(row.total_deductions or 0.0),
            "total_net": float(row.total_net or 0.0),
            "processed_count": int(row.processed_count or 0),
            "paid_count": int(row.paid_count or 0),
        }
