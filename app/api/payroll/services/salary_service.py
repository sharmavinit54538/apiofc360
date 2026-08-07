"""Service handling employee salary structures."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.exceptions import NotFoundException
from app.api.payroll.repositories.salary_repository import SalaryRepository
from app.api.payroll.serializers import _salary_dict


class SalaryService:
    """Business logic for SalaryStructure management."""

    def __init__(self, db: AsyncSession):
        self.repo = SalaryRepository(db)

    async def get_by_employee(self, employee_id: uuid.UUID) -> dict:
        """Get active salary structure for employee."""
        salary = await self.repo.get_by_employee_id(employee_id)
        if not salary:
            raise NotFoundException("Salary structure not found for employee.")
        return _salary_dict(salary)

    async def list_structures(self, limit: int = 50) -> list[dict]:
        """List active salary structures."""
        structures = await self.repo.list_structures(limit)
        return [_salary_dict(s) for s in structures]
