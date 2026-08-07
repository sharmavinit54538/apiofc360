"""Database repository for DeductionComponent entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import DeductionComponent


class DeductionRepository:
    """SQLAlchemy Repository for DeductionComponent entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_deductions(self) -> Sequence[DeductionComponent]:
        """List all deduction components."""
        stmt = select(DeductionComponent)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_by_id(self, deduction_id: uuid.UUID) -> Optional[DeductionComponent]:
        """Fetch deduction component by ID."""
        stmt = select(DeductionComponent).where(DeductionComponent.id == deduction_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
