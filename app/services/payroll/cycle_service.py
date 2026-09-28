"""Service for Payroll Cycles management."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional
from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayCycle
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class PayrollCycleService:
    """Business logic for Pay Cycles."""

    @classmethod
    async def get_cycle(cls, session: AsyncSession, cycle_id: uuid.UUID) -> PayCycle:
        stmt = select(PayCycle).where(PayCycle.id == cycle_id)
        cycle = (await session.execute(stmt)).scalar_one_or_none()
        if not cycle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll cycle '{cycle_id}' not found.",
            )
        return cycle

    @classmethod
    async def list_cycles(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        status_filter: Optional[str] = None,
    ) -> list[PayCycle]:
        stmt = select(PayCycle)
        if company_id:
            stmt = stmt.where(PayCycle.company_id == company_id)
        if status_filter:
            stmt = stmt.where(PayCycle.status == status_filter.upper())
        stmt = stmt.order_by(desc(PayCycle.period_year), desc(PayCycle.period_month))
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def reopen_cycle(
        cls,
        session: AsyncSession,
        cycle_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayCycle:
        cycle = await cls.get_cycle(session, cycle_id)
        old_status = cycle.status
        cycle.status = "DRAFT"
        cycle.is_locked = False
        cycle.remarks = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayCycle",
            entity_id=cycle.id,
            action="REOPEN",
            company_id=cycle.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="DRAFT",
            reason=reason,
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
    ) -> PayCycle:
        cycle = await cls.get_cycle(session, cycle_id)
        old_status = cycle.status
        cycle.status = "VOID"
        cycle.is_active = False
        cycle.remarks = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayCycle",
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
