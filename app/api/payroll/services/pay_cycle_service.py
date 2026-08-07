"""Service handling PayCycle lifecycle operations."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.exceptions import NotFoundException
from app.api.payroll.repositories.payroll_repository import PayrollRepository
from app.api.payroll.serializers import _run_dict
from app.models.payroll import PayCycle


class PayCycleService:
    """Business logic for PayCycle management."""

    def __init__(self, db: AsyncSession):
        self.repo = PayrollRepository(db)

    async def list_cycles(self, month: Optional[int] = None, year: Optional[int] = None) -> list[dict]:
        """Get serialized list of pay cycles."""
        cycles = await self.repo.list_cycles(month, year)
        return [_run_dict(c) for c in cycles]

    async def get_cycle(self, cycle_id: uuid.UUID) -> dict:
        """Get serialized details for a single pay cycle."""
        cycle = await self.repo.get_cycle_by_id(cycle_id)
        if not cycle:
            raise NotFoundException("Pay cycle not found.")
        return _run_dict(cycle)

    async def create_cycle(self, data: dict, user_id: Optional[uuid.UUID]) -> dict:
        """Create new pay cycle in DRAFT state."""
        cycle = PayCycle(
            period_month=data.get("period_month", 1),
            period_year=data.get("period_year", 2026),
            status="DRAFT",
            total_employees=0,
            total_gross=0.0,
            total_deductions=0.0,
            total_net=0.0,
            run_by=user_id,
        )
        created = await self.repo.create_cycle(cycle)
        return _run_dict(created)
