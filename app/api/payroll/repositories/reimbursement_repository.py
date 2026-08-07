"""Database repository for ReimbursementClaim entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import ReimbursementClaim


class ReimbursementRepository:
    """SQLAlchemy Repository for ReimbursementClaim entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_claims(self, employee_id: Optional[uuid.UUID] = None) -> Sequence[ReimbursementClaim]:
        """List reimbursement claims."""
        stmt = select(ReimbursementClaim)
        if employee_id:
            stmt = stmt.where(ReimbursementClaim.employee_id == employee_id)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_by_id(self, claim_id: uuid.UUID) -> Optional[ReimbursementClaim]:
        """Fetch claim by ID."""
        stmt = select(ReimbursementClaim).where(ReimbursementClaim.id == claim_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
