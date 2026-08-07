"""Database repository for BonusPlan and BonusAward entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import BonusAward, BonusPlan


class BonusRepository:
    """SQLAlchemy Repository for Bonus entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_plans(self) -> Sequence[BonusPlan]:
        """List all bonus plans."""
        stmt = select(BonusPlan)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_plan_by_id(self, plan_id: uuid.UUID) -> Optional[BonusPlan]:
        """Fetch bonus plan by ID."""
        stmt = select(BonusPlan).where(BonusPlan.id == plan_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_awards(self, employee_id: Optional[uuid.UUID] = None) -> Sequence[BonusAward]:
        """List bonus awards."""
        stmt = select(BonusAward)
        if employee_id:
            stmt = stmt.where(BonusAward.employee_id == employee_id)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_award_by_id(self, award_id: uuid.UUID) -> Optional[BonusAward]:
        """Fetch bonus award by ID."""
        stmt = select(BonusAward).where(BonusAward.id == award_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
