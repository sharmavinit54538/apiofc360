"""Accounting router for Payroll v2."""

from __future__ import annotations

import uuid
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
