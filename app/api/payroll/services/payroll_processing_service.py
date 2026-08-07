"""Service handling salary calculations and payroll processing runs."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.exceptions import NotFoundException
from app.api.payroll.repositories.payroll_repository import PayrollRepository


class PayrollProcessingService:
    """Business logic for triggering and executing payroll calculation runs."""

    def __init__(self, db: AsyncSession):
        self.repo = PayrollRepository(db)

    async def trigger_run(self, body: dict) -> dict:
        """Trigger salary processing run."""
        run_id = str(uuid.uuid4())
        return {
            "run_id": run_id,
            "status": "PROCESSING",
            "message": "Payroll processing run initiated.",
        }

    async def approve_run(self, run_id: uuid.UUID) -> dict:
        """Approve salary processing run."""
        return {
            "run_id": str(run_id),
            "status": "APPROVED",
            "message": "Salary processing run approved.",
        }

    async def rollback_run(self, run_id: uuid.UUID) -> dict:
        """Rollback salary processing run."""
        return {
            "run_id": str(run_id),
            "status": "ROLLED_BACK",
            "message": "Salary processing run rolled back.",
        }
