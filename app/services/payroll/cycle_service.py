"""Service for Payroll Periods management (canonical period entity).

Replaces PayCycle - all operations now on PayrollPeriod.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional
from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayrollRun, PayrollAuditLog
from app.models.payroll_models import PayrollPeriod
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class PayrollCycleService:
    """Business logic for Payroll Periods (canonical)."""

    @classmethod
    async def get_cycle(cls, session: AsyncSession, cycle_id: uuid.UUID) -> PayrollPeriod:
        stmt = select(PayrollPeriod).where(PayrollPeriod.id == cycle_id)
        cycle = (await session.execute(stmt)).scalar_one_or_none()
        if not cycle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll period '{cycle_id}' not found.",
            )
        return cycle

    @classmethod
    async def list_cycles(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        stmt = select(PayrollPeriod)
        if company_id:
            stmt = stmt.where(PayrollPeriod.company_id == company_id)
        if status_filter:
            stmt = stmt.where(func.upper(PayrollPeriod.status) == status_filter.upper())
        stmt = stmt.order_by(desc(PayrollPeriod.period_year), desc(PayrollPeriod.period_month))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * page_size)
        stmt = stmt.offset(offset).limit(page_size)
        items = list((await session.execute(stmt)).scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @classmethod
    async def create_cycle(
        cls,
        session: AsyncSession,
        company_id: uuid.UUID,
        name: str,
        frequency: str,
        period_month: int,
        period_year: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        processing_date: Optional[date] = None,
        payment_date: Optional[date] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollPeriod:
        # Check for duplicate period for same company/period
        existing = await session.execute(
            select(PayrollPeriod).where(
                PayrollPeriod.company_id == company_id,
                PayrollPeriod.period_month == period_month,
                PayrollPeriod.period_year == period_year,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Payroll period for {period_month}/{period_year} already exists.",
            )

        # Defaults: processing_date = end_date, payment_date = pay_date
        processing_date = processing_date or end_date
        payment_date = payment_date or pay_date

        cycle = PayrollPeriod(
            id=uuid.uuid4(),
            company_id=company_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            pay_date=pay_date,
            processing_date=processing_date,
            payment_date=payment_date,
            period_month=period_month,
            period_year=period_year,
            status="OPEN",
            is_locked=False,
            remarks=None,
        )
        session.add(cycle)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollPeriod",
            entity_id=cycle.id,
            action="CREATE",
            company_id=company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=None,
            after_status="OPEN",
            reason="Payroll period created",
        )
        await session.commit()
        await session.refresh(cycle)
        return cycle

    @classmethod
    async def reopen_cycle(
        cls,
        session: AsyncSession,
        cycle_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollPeriod:
        cycle = await cls.get_cycle(session, cycle_id)
        
        # Status guard: can only reopen from LOCKED, CLOSED, PROCESSING
        if cycle.status not in ("LOCKED", "CLOSED", "PROCESSING"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Period in '{cycle.status}' state cannot be reopened.",
            )

        old_status = cycle.status
        cycle.status = "OPEN"
        cycle.is_locked = False
        cycle.locked_by = None
        cycle.locked_at = None
        cycle.remarks = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollPeriod",
            entity_id=cycle.id,
            action="REOPEN",
            company_id=cycle.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="OPEN",
            reason=reason,
        )
        await session.commit()
        await session.refresh(cycle)
        return cycle

    @classmethod
    async def lock_cycle(
        cls,
        session: AsyncSession,
        cycle_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollPeriod:
        cycle = await cls.get_cycle(session, cycle_id)
        
        # Status guard: can only lock from OPEN
        if cycle.status != "OPEN":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Period in '{cycle.status}' state cannot be locked.",
            )

        old_status = cycle.status
        cycle.status = "LOCKED"
        cycle.is_locked = True
        cycle.locked_by = user_id
        cycle.locked_at = datetime.now()

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollPeriod",
            entity_id=cycle.id,
            action="LOCK",
            company_id=cycle.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="LOCKED",
            reason="Payroll period locked",
        )
        await session.commit()
        await session.refresh(cycle)
        return cycle

    @classmethod
    async def void_cycle(
        cls,
        session: AsyncSession,
        cycle_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollPeriod:
        cycle = await cls.get_cycle(session, cycle_id)
        
        # Check if non-cancelled runs exist
        from app.models.payroll import PayrollRun
        runs_stmt = select(PayrollRun).where(
            PayrollRun.period_id == cycle_id,
            PayrollRun.status.notin_(["CANCELLED", "VOID", "REJECTED"])
        )
        existing_runs = (await session.execute(runs_stmt)).scalars().all()
        if existing_runs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot void period with active payroll runs. Cancel or delete runs first.",
            )

        old_status = cycle.status
        cycle.status = "VOID"
        cycle.is_active = False
        cycle.remarks = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollPeriod",
            entity_id=cycle.id,
            action="VOID",
            company_id=cycle.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="VOID",
            reason=reason,
        )
        await session.commit()
        await session.refresh(cycle)
        return cycle

    @classmethod
    async def get_logs(cls, session: AsyncSession, limit: int = 100) -> list[dict]:
        stmt = select(PayrollAuditLog).where(
            PayrollAuditLog.entity_type == "PayrollPeriod"
        ).order_by(desc(PayrollAuditLog.created_at)).limit(limit)
        res = await session.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "cycle_id": str(l.entity_id) if l.entity_id else None,
                "action": l.action,
                "actor": l.actor_role or "System Admin",
                "previous_value": l.old_status or "None",
                "updated_value": l.new_status or "Updated",
                "ip_address": l.extra_data.get("ip", "127.0.0.1") if l.extra_data else "127.0.0.1",
                "browser": l.extra_data.get("browser", "Dashboard Web") if l.extra_data else "Dashboard Web",
                "reason": l.reason or "Payroll period operation",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
