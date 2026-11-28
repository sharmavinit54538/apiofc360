"""Company Bank Accounts router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _reject_super_admin, _require_admin_or_manager, _require_tenant_id
from app.db.database import get_db_session
from app.services.payroll.company_bank_service import CompanyBankService
from app.services.payroll.payment_batch_service import mask_bank_account

router = APIRouter(tags=["Payroll v2 - Company Bank"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _serialize_company_bank_accounts(accounts: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(acc.id),
            "company_id": str(acc.company_id),
            "bank_name": acc.bank_name,
            "account_number_masked": mask_bank_account(getattr(acc, "account_number", None)) or "••••",
            "ifsc_code": acc.ifsc_code,
            "account_holder_name": acc.account_holder_name,
            "account_type": getattr(acc, "account_type", "CURRENT") or "CURRENT",
            "currency": getattr(acc, "currency", "INR") or "INR",
            "supported_payment_modes": getattr(acc, "supported_payment_modes", None) or ["NEFT", "RTGS", "IMPS"],
            "is_primary": acc.is_primary,
            "is_active": acc.is_active,
        }
        for acc in accounts
    ]


# GET /api/v2/payroll/company-bank-accounts
@router.get("/company-bank-accounts", summary="Get tenant company bank accounts")
async def list_tenant_company_bank_accounts(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    _reject_super_admin(claims)
    tenant_id = _require_tenant_id(claims)
    accounts = await CompanyBankService.get_company_bank_accounts(db, company_id=tenant_id)
    return _ok(_serialize_company_bank_accounts(accounts), "Company bank accounts retrieved successfully")


# GET /api/v2/payroll/companies/{companyId}/bank-accounts
@router.get("/companies/{companyId}/bank-accounts", summary="Get company bank accounts")
async def get_company_bank_accounts(
    companyId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    _reject_super_admin(claims)
    # Multi-tenancy rule: the path parameter may never widen the caller's tenant.
    # A request for another organization's bank accounts answers 404 (not 403) so
    # the existence of another tenant's records is not disclosed.
    tenant_id = None
    if claims and claims.get("company_id"):
        try:
            tenant_id = uuid.UUID(str(claims["company_id"]))
        except (ValueError, TypeError):
            tenant_id = None
    if tenant_id is None or tenant_id != companyId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company '{companyId}' not found.",
        )
    accounts = await CompanyBankService.get_company_bank_accounts(db, company_id=companyId)
    return _ok(_serialize_company_bank_accounts(accounts), "Company bank accounts retrieved successfully")
