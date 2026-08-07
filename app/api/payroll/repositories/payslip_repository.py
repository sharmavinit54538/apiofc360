"""Database repository for Payslip entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import Payslip


class PayslipRepository:
    """SQLAlchemy Repository for Payslip entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, payslip_id: uuid.UUID) -> Optional[Payslip]:
        """Fetch payslip by ID."""
        stmt = select(Payslip).where(Payslip.id == payslip_id).options(selectinload(Payslip.employee))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_payslips(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[Payslip], int]:
        """List payslips with pagination for month/year."""
        m = month if isinstance(month, int) else None
        y = year if isinstance(year, int) else None

        stmt = select(Payslip).options(selectinload(Payslip.employee))
        count_stmt = select(func.count(Payslip.id))

        if m is not None:
            stmt = stmt.where(Payslip.period_month == m)
            count_stmt = count_stmt.where(Payslip.period_month == m)
        if y is not None:
            stmt = stmt.where(Payslip.period_year == y)
            count_stmt = count_stmt.where(Payslip.period_year == y)

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        res = await self.db.execute(stmt)
        payslips = res.scalars().all()

        count_res = await self.db.execute(count_stmt)
        total = count_res.scalar() or 0

        return payslips, total

    async def get_employee_payslip(self, employee_id: uuid.UUID, month: int, year: int) -> Optional[Payslip]:
        """Fetch single employee payslip."""
        stmt = select(Payslip).where(
            Payslip.employee_id == employee_id,
            Payslip.period_month == month,
            Payslip.period_year == year
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
