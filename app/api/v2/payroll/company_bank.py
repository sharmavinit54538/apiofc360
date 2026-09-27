"""Company Bank Accounts router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.services.payroll.company_bank_service import CompanyBankService

router = APIRouter(tags=["Payroll v2 - Company Bank"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# GET /api/v2/payroll/companies/{companyId}/bank-accounts
@router.get("/companies/{companyId}/bank-accounts", summary="Get company bank accounts")
async def get_company_bank_accounts(
    companyId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    accounts = await CompanyBankService.get_company_bank_accounts(db, company_id=companyId)
    data = [
        {
            "id": str(acc.id),
            "company_id": str(acc.company_id),
            "bank_name": acc.bank_name,
            "account_number": acc.account_number,
            "ifsc_code": acc.ifsc_code,
            "account_holder_name": acc.account_holder_name,
            "account_type": acc.account_type,
            "is_primary": acc.is_primary,
            "is_active": acc.is_active,
        }
        for acc in accounts
    ]
    return _ok(data, "Company bank accounts retrieved successfully")
