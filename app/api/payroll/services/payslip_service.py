"""Service handling payslip generation and retrieval."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.exceptions import NotFoundException
from app.api.payroll.repositories.payslip_repository import PayslipRepository
from app.api.payroll.serializers import _payslip_dict


class PayslipService:
    """Business logic for payslip queries and bulk PDF/email generation."""

    def __init__(self, db: AsyncSession):
        self.repo = PayslipRepository(db)

    async def get_by_id(self, payslip_id: uuid.UUID) -> dict:
        """Fetch serialized payslip by ID."""
        payslip = await self.repo.get_by_id(payslip_id)
        if not payslip:
            raise NotFoundException("Payslip not found.")
        return _payslip_dict(payslip)

    async def list_payslips(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """List payslips for a period with pagination."""
        payslips, total = await self.repo.list_payslips(month, year, page, page_size)
        items = [_payslip_dict(p) for p in payslips]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
