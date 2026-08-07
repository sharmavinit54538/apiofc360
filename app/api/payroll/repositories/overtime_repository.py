"""Database repository for OvertimePolicy and OvertimeEntry entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import OvertimeEntry, OvertimePolicy


class OvertimeRepository:
    """SQLAlchemy Repository for Overtime entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_policies(self) -> Sequence[OvertimePolicy]:
        """List overtime policies."""
        stmt = select(OvertimePolicy)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_policy_by_id(self, policy_id: uuid.UUID) -> Optional[OvertimePolicy]:
        """Fetch policy by ID."""
        stmt = select(OvertimePolicy).where(OvertimePolicy.id == policy_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_entries(self, employee_id: Optional[uuid.UUID] = None) -> Sequence[OvertimeEntry]:
        """List overtime entries."""
        stmt = select(OvertimeEntry)
        if employee_id:
            stmt = stmt.where(OvertimeEntry.employee_id == employee_id)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_entry_by_id(self, entry_id: uuid.UUID) -> Optional[OvertimeEntry]:
        """Fetch overtime entry by ID."""
        stmt = select(OvertimeEntry).where(OvertimeEntry.id == entry_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
