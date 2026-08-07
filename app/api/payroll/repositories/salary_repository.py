"""Database repository for SalaryStructure entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import SalaryStructure


class SalaryRepository:
    """SQLAlchemy Repository for SalaryStructure entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_employee_id(self, employee_id: uuid.UUID) -> Optional[SalaryStructure]:
        """Get active salary structure for employee."""
        stmt = select(SalaryStructure).where(
            SalaryStructure.employee_id == employee_id,
            SalaryStructure.is_active == True
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_structure(self, structure: SalaryStructure) -> SalaryStructure:
        """Create and commit a new salary structure."""
        self.db.add(structure)
        await self.db.commit()
        await self.db.refresh(structure)
        return structure

    async def list_structures(self, limit: int = 50) -> Sequence[SalaryStructure]:
        """List active salary structures."""
        stmt = select(SalaryStructure).where(SalaryStructure.is_active == True).limit(limit)
        res = await self.db.execute(stmt)
        return res.scalars().all()
