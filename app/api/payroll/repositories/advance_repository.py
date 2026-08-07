"""Database repository for BankDisbursementRecord and Advance/Loan entities."""
from __future__ import annotations

import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import BankDisbursementRecord


class AdvanceRepository:
    """SQLAlchemy Repository for Advance/Loan and Bank Disbursement entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_disbursements(self, run_id: Optional[uuid.UUID] = None) -> Sequence[BankDisbursementRecord]:
        """List bank disbursement records."""
        stmt = select(BankDisbursementRecord)
        if run_id:
            stmt = stmt.where(BankDisbursementRecord.payroll_run_id == run_id)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_disbursement_by_id(self, record_id: uuid.UUID) -> Optional[BankDisbursementRecord]:
        """Fetch bank disbursement record by ID."""
        stmt = select(BankDisbursementRecord).where(BankDisbursementRecord.id == record_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
