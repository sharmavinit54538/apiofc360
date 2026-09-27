"""Variable Inputs router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.variable_inputs import (
    VariableInputApproveRequest,
    VariableInputBulkApplyRequest,
    VariableInputCreateRequest,
    VariableInputRejectRequest,
)
from app.services.payroll.variable_input_service import VariableInputService

router = APIRouter(tags=["Payroll v2 - Variable Inputs"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _var_dict(item) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "employee_id": str(item.employee_id),
        "period_id": str(item.period_id),
        "company_id": str(item.company_id) if item.company_id else None,
        "type": item.type,
        "amount_paise": item.amount_paise,
        "units": float(item.units) if item.units is not None else None,
        "rate_per_unit_paise": item.rate_per_unit_paise,
        "description": item.description,
        "status": item.status,
        "approved_by": str(item.approved_by) if item.approved_by else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "remarks": item.remarks,
        "rejected_by": str(item.rejected_by) if item.rejected_by else None,
        "rejected_at": item.rejected_at.isoformat() if item.rejected_at else None,
        "rejection_reason": item.rejection_reason,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


# 1. GET /api/v2/payroll/variable-inputs
@router.get("/variable-inputs", summary="List variable salary inputs")
async def list_variable_inputs(
    periodId: Optional[uuid.UUID] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await VariableInputService.list_inputs(
        session=db,
        company_id=c_uuid,
        period_id=periodId,
        input_type=type,
        status_filter=status,
        search=search,
        page=page,
        limit=limit,
    )
    items = [_var_dict(i) for i in res["items"]]
    return _ok({
        "items": items,
        "total": res["total"],
        "page": res["page"],
        "limit": res["limit"],
    }, "Variable inputs retrieved successfully")


# 2. POST /api/v2/payroll/variable-inputs
@router.post("/variable-inputs", status_code=status.HTTP_201_CREATED, summary="Create a new variable input")
async def create_variable_input(
    payload: VariableInputCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    item = await VariableInputService.create_input(
        session=db,
        payload=payload,
        company_id=c_uuid,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_var_dict(item), "Variable input created successfully")


# 3. POST /api/v2/payroll/variable-inputs/bulk-preview
@router.post("/variable-inputs/bulk-preview", summary="Preview bulk variable inputs file")
async def preview_variable_inputs_bulk(
    file: UploadFile = File(..., description="CSV or Excel file with variable inputs"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    preview = await VariableInputService.preview_bulk_inputs(
        session=db, file=file, company_id=c_uuid
    )
    return _ok(preview, "Bulk variable inputs preview generated successfully")


# 4. POST /api/v2/payroll/variable-inputs/bulk-apply
@router.post("/variable-inputs/bulk-apply", summary="Apply bulk variable inputs from preview token")
async def apply_variable_inputs_bulk(
    payload: VariableInputBulkApplyRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await VariableInputService.apply_bulk_inputs(
        session=db,
        preview_token=payload.preview_token,
        company_id=c_uuid,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(res, "Bulk variable inputs applied successfully")


# 5. POST /api/v2/payroll/variable-inputs/{id}/approve
@router.post("/variable-inputs/{id}/approve", summary="Approve variable input")
async def approve_variable_input(
    id: uuid.UUID,
    payload: Optional[VariableInputApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    remarks = payload.remarks if payload else None
    item = await VariableInputService.approve_input(
        session=db,
        input_id=id,
        user_id=user_id,
        user_role=user_role,
        remarks=remarks,
    )
    return _ok(_var_dict(item), "Variable input approved successfully")


# 6. POST /api/v2/payroll/variable-inputs/{id}/reject
@router.post("/variable-inputs/{id}/reject", summary="Reject variable input")
async def reject_variable_input(
    id: uuid.UUID,
    payload: VariableInputRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    item = await VariableInputService.reject_input(
        session=db,
        input_id=id,
        user_id=user_id,
        user_role=user_role,
        reason=payload.reason,
    )
    return _ok(_var_dict(item), "Variable input rejected")
