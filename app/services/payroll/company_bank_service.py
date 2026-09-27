"""Service for managing Company Bank Accounts."""

from __future__ import annotations

import logging
import uuid
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll_models import CompanyBankAccount

logger = logging.getLogger(__name__)


class CompanyBankService:
    """Business logic for organizational bank accounts."""

    @classmethod
    async def get_company_bank_accounts(
        cls, session: AsyncSession, company_id: uuid.UUID
    ) -> List[CompanyBankAccount]:
        stmt = (
            select(CompanyBankAccount)
            .where(
                CompanyBankAccount.company_id == company_id,
                CompanyBankAccount.is_active == True,
            )
        )
        accounts = list((await session.execute(stmt)).scalars().all())
        if not accounts:
            # Seed default primary company bank account for this company
            default_acc = CompanyBankAccount(
                id=uuid.uuid4(),
                company_id=company_id,
                bank_name="HDFC Bank",
                account_number="50200012345678",
                ifsc_code="HDFC0001234",
                account_holder_name="OFC360 Enterprise Solutions Pvt Ltd",
                account_type="CURRENT",
                is_primary=True,
                is_active=True,
            )
            session.add(default_acc)
            await session.commit()
            await session.refresh(default_acc)
            accounts = [default_acc]

        return accounts
