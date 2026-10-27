"""Retroactive attendance/leave/salary adjustments and arrear carry-forward."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayrollAttendanceInput, SalaryStructure
from app.models.payroll_models import ArrearLedger, Compensation, PayrollPeriod
from app.services.payroll.money import as_decimal, round_paise


class ArrearService:
    TYPES = frozenset({"ATTENDANCE_RETRO", "LEAVE_REVERSAL", "SALARY_REVISION"})
    STATUSES = frozenset({"PENDING", "APPLIED", "CANCELLED"})

    @classmethod
    async def next_open_period(
        cls,
        session: AsyncSession,
        *,
        company_id: Optional[uuid.UUID],
        source_period_id: Optional[uuid.UUID],
    ) -> Optional[PayrollPeriod]:
        source = None
        if source_period_id:
            source = await session.get(PayrollPeriod, source_period_id)
        stmt = select(PayrollPeriod).where(PayrollPeriod.status == "OPEN")
        if company_id is not None:
            stmt = stmt.where(PayrollPeriod.company_id == company_id)
        if source is not None:
            stmt = stmt.where(
                (PayrollPeriod.period_year > source.period_year)
                | (
                    (PayrollPeriod.period_year == source.period_year)
                    & (PayrollPeriod.period_month > source.period_month)
                )
            )
        stmt = stmt.order_by(PayrollPeriod.period_year, PayrollPeriod.period_month).limit(1)
        return (await session.execute(stmt)).scalars().first()

    @classmethod
    async def daily_rate_paise(cls, session: AsyncSession, employee_id: uuid.UUID) -> int:
        """Use monthly gross / 30 for retroactive day adjustments."""
        comp = (await session.execute(
            select(Compensation).where(
                Compensation.employee_id == employee_id,
                Compensation.status == "ACTIVE",
            )
        )).scalars().first()
        if comp is not None:
            monthly = int(comp.basic_monthly_paise or 0) + int(comp.hra_monthly_paise or 0) + int(comp.special_allowance_monthly_paise or 0)
            if monthly:
                return round_paise(Decimal(monthly) / Decimal("30"))
        salary = (await session.execute(
            select(SalaryStructure).where(
                SalaryStructure.employee_id == employee_id,
                SalaryStructure.is_active == True,  # noqa: E712
            )
        )).scalars().first()
        if salary is not None:
            monthly = sum(as_decimal(getattr(salary, f, 0)) for f in (
                "basic_monthly", "hra_monthly", "special_allowance_monthly", "conveyance_monthly"
            )) * 100
            return round_paise(monthly / Decimal("30"))
        return 0

    @classmethod
    async def create_arrear(
        cls,
        session: AsyncSession,
        *,
        employee_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
        source_period_id: Optional[uuid.UUID] = None,
        target_period_id: Optional[uuid.UUID] = None,
        arrear_type: str = "ATTENDANCE_RETRO",
        delta_days: Any = Decimal("0"),
        amount_paise: Optional[int] = None,
        calculation_json: Optional[dict[str, Any]] = None,
        created_by: Optional[uuid.UUID] = None,
        daily_rate_paise: Optional[int] = None,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        type: Optional[str] = None,
    ) -> ArrearLedger:
        """Create a pending signed-paise arrear and assign its next open period."""
        source_period_id = source_period_id or source_id
        target_period_id = target_period_id or target_id
        arrear_type = str(type or arrear_type).upper()
        if arrear_type not in cls.TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported arrear type '{arrear_type}'.")
        days = as_decimal(delta_days)
        if amount_paise is None:
            rate = daily_rate_paise if daily_rate_paise is not None else await cls.daily_rate_paise(session, employee_id)
            amount_paise = round_paise(Decimal(rate) * days)
        amount_paise = int(amount_paise)
        if target_period_id is None:
            target = await cls.next_open_period(session, company_id=company_id, source_period_id=source_period_id)
            target_period_id = target.id if target else None
        details = dict(calculation_json or {})
        details.setdefault("delta_days", str(days))
        details.setdefault("daily_rate_paise", daily_rate_paise)
        details.setdefault("amount_paise", amount_paise)
        row = ArrearLedger(
            id=uuid.uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            source_period_id=source_period_id,
            target_period_id=target_period_id,
            type=arrear_type,
            delta_days=days,
            amount_paise=amount_paise,
            status="PENDING",
            calculation_json=details,
            created_by=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def create_retroactive_arrear(cls, session: AsyncSession, **kwargs) -> ArrearLedger:
        return await cls.create_arrear(session, **kwargs)

    @classmethod
    async def pending_for_run(cls, session: AsyncSession, run) -> list[ArrearLedger]:
        """Claim rows targeted at this period, including unassigned older rows."""
        if not run.period_id:
            return []
        stmt = select(ArrearLedger).where(
            ArrearLedger.status == "PENDING",
            (ArrearLedger.target_period_id == run.period_id) | ArrearLedger.target_period_id.is_(None),
        )
        if run.company_id is not None:
            stmt = stmt.where(ArrearLedger.company_id == run.company_id)
        rows = list((await session.execute(stmt)).scalars().all())
        eligible: list[ArrearLedger] = []
        for row in rows:
            if row.target_period_id is None and row.source_period_id is not None:
                source = await session.get(PayrollPeriod, row.source_period_id)
                if source is not None and (source.period_year, source.period_month) >= (run.period_year, run.period_month):
                    continue
            row.target_period_id = run.period_id
            eligible.append(row)
        return eligible

    @classmethod
    def mark_applied(cls, rows: list[ArrearLedger], run_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "APPLIED"
            row.applied_run_id = run_id
            row.applied_at = now

    @classmethod
    async def cancel(cls, session: AsyncSession, arrear_id: uuid.UUID, reason: str = "Cancelled") -> ArrearLedger:
        row = await session.get(ArrearLedger, arrear_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Arrear entry not found.")
        if row.status != "PENDING":
            raise HTTPException(status_code=409, detail="Only pending arrears can be cancelled.")
        row.status = "CANCELLED"
        row.calculation_json = {**(row.calculation_json or {}), "cancellation_reason": reason}
        await session.flush()
        return row


# Domain-friendly alias for callers that use the longer service name.
ArrearLedgerService = ArrearService
