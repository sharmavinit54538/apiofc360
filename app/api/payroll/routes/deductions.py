"""Route handlers for deductions components."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.deduction_service import DeductionService
from app.schemas.auth import APIResponse

router = APIRouter()


@router.get("/deductions", response_model=APIResponse[dict], summary="List deductions")
@router.head("/deductions")
async def list_deductions(
    categoryGroup: Optional[str] = Query(None),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = DeductionService(db)
    items = await service.list_deductions(categoryGroup=categoryGroup)
    return success_response({"items": items, "total": len(items)}, "Deductions retrieved.")
