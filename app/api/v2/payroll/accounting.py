"""Accounting router for Payroll v2."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.services.payroll.accounting_service import AccountingService

router = APIRouter(tags=["Payroll v2 - Accounting"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# GET /api/v2/payroll/accounting-export
@router.get("/accounting-export", summary="Export general ledger accounting journal entries")
async def export_accounting_entries(
    periodId: uuid.UUID = Query(..., description="Payroll period UUID"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await AccountingService.export_accounting_entries(db, period_id=periodId, company_id=c_uuid)
    return _ok(res, "Accounting entries exported successfully")


# ---------------------------------------------------------------------------
# Batch 6: tenant GL maps, balanced journals, exports, and reconciliation
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field
from app.api.v2.enterprise_dependencies import company_id as _tenant_id, translate as _translate
from app.services.payroll.accounting_service import EnterpriseAccountingService


class GLMappingRequest(BaseModel):
    provider: str
    source_key: str
    account_code: str
    account_name: str
    account_type: str


class JournalRequest(BaseModel):
    period_id: uuid.UUID
    provider: str = "GENERIC"


class AccountingExportRequest(BaseModel):
    period_id: uuid.UUID
    export_format: str


class ExpensePostingRequest(BaseModel):
    expense_date: date
    category: str
    amount_paise: int = Field(gt=0)
    description: str
    idempotency_key: str = Field(min_length=8)
    employee_id: uuid.UUID | None = None
    external_reference: str | None = None


class ReconciliationRequest(BaseModel):
    period_id: uuid.UUID
    provider: str
    external_entries: list[dict]


@router.post("/gl-mappings", status_code=201)
async def create_gl_mapping(body: GLMappingRequest, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    try:
        row = await EnterpriseAccountingService(db).upsert_mapping(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(row.id), "source_key": row.source_key, "account_code": row.account_code})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/journals/build")
async def build_payroll_journal(body: JournalRequest, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    try:
        journal = await EnterpriseAccountingService(db).build_journal(company_id=_tenant_id(claims), **body.model_dump())
        return _ok(journal)
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/journals/export")
async def export_enterprise_journal(body: AccountingExportRequest, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    try:
        result = await EnterpriseAccountingService(db).export_journal(company_id=_tenant_id(claims), **body.model_dump())
        return _ok(result)
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/expenses", status_code=201)
async def post_expense(body: ExpensePostingRequest, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    try:
        expense = await EnterpriseAccountingService(db).post_expense(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(expense.id), "status": expense.status, "amount_paise": expense.amount_paise})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/reconciliations", status_code=201)
async def reconcile_gl(body: ReconciliationRequest, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    try:
        row = await EnterpriseAccountingService(db).reconcile_gl(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(row.id), "status": row.status, "difference_paise": row.difference_paise})
    except (ValueError, LookupError) as exc:
        _translate(exc)
