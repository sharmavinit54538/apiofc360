"""Service for managing Payroll Periods (v1 & v2)."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.payroll_models import PayrollPeriod
from app.schemas.payroll_v2.periods import PayrollPeriodCreateRequest


class PayrollPeriodService:
    """Business logic for Payroll Periods."""

    @classmethod
    async def list_periods(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = select(PayrollPeriod)
        if company_id:
            stmt = stmt.where(
                or_(PayrollPeriod.company_id == company_id, PayrollPeriod.company_id.is_(None))
            )
        if status_filter:
            stmt = stmt.where(func.upper(PayrollPeriod.status) == status_filter.upper())
        if year:
            stmt = stmt.where(PayrollPeriod.period_year == year)
        if month:
            stmt = stmt.where(PayrollPeriod.period_month == month)
        if search:
            stmt = stmt.where(PayrollPeriod.name.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(PayrollPeriod.period_year), desc(PayrollPeriod.period_month), desc(PayrollPeriod.created_at))
        stmt = stmt.offset(offset).limit(limit)

        result = await session.execute(stmt)
        periods = result.scalars().all()

        return {
            "items": periods,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def get_period(cls, session: AsyncSession, period_id: uuid.UUID) -> PayrollPeriod:
        stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        result = await session.execute(stmt)
        period = result.scalar_one_or_none()
        if not period:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll period '{period_id}' not found.",
            )
        return period

    @classmethod
    async def create_period(
        cls,
        session: AsyncSession,
        payload: PayrollPeriodCreateRequest,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollPeriod:
        # Determine month and year from pay_date or start_date if not provided
        p_month = payload.period_month or payload.start_date.month
        p_year = payload.period_year or payload.start_date.year

        target_company_id = company_id
        if payload.company_id:
            try:
                target_company_id = uuid.UUID(str(payload.company_id))
            except ValueError:
                pass

        period = PayrollPeriod(
            id=uuid.uuid4(),
            company_id=target_company_id,
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            pay_date=payload.pay_date,
            period_month=p_month,
            period_year=p_year,
            status="OPEN",
            remarks=payload.remarks,
        )
        session.add(period)
        await session.commit()
        await session.refresh(period)
        return period
