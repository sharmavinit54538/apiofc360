"""Compensation router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.compensation import (
    CompensationBulkImportApplyRequest,
    CompensationRevisionApproveRequest,
    CompensationRevisionRejectRequest,
)
from app.services.payroll.compensation_service import CompensationService

router = APIRouter(tags=["Payroll v2 - Compensation"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# GET /api/v2/payroll/compensations
@router.get("/compensations", summary="List employee compensations")
async def list_compensations(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    department: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await CompensationService.list_compensations(
        session=db,
        company_id=c_uuid,
        page=page,
        limit=limit,
        department=department,
        search=search,
    )
    return _ok(res, "Compensations retrieved successfully")


# POST /api/v2/payroll/compensation/bulk-import/preview
@router.post("/compensation/bulk-import/preview", summary="Preview bulk compensation import file")
async def preview_compensation_bulk_import(
    file: UploadFile = File(..., description="CSV or XLSX file for compensation import"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await CompensationService.preview_bulk_import(session=db, file=file, company_id=c_uuid)
    return _ok(res, "Bulk import preview generated successfully")


# POST /api/v2/payroll/compensation/bulk-import/apply
@router.post("/compensation/bulk-import/apply", summary="Apply bulk compensation import from preview token")
async def apply_compensation_bulk_import(
    payload: CompensationBulkImportApplyRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await CompensationService.apply_bulk_import(
        session=db,
        preview_token=payload.preview_token,
        company_id=c_uuid,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(res, "Bulk compensation import applied successfully")


# POST /api/v2/payroll/compensation/revisions/{revisionId}/approve
@router.post("/compensation/revisions/{revisionId}/approve", summary="Approve compensation revision")
async def approve_compensation_revision(
    revisionId: uuid.UUID,
    payload: Optional[CompensationRevisionApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    remarks = payload.remarks if payload else None
    rev = await CompensationService.approve_revision(
        session=db,
        revision_id=revisionId,
        user_id=user_id,
        user_role=user_role,
        remarks=remarks,
    )
    return _ok({
        "id": str(rev.id),
        "employee_id": str(rev.employee_id),
        "status": rev.status,
        "new_ctc_annual_paise": rev.new_ctc_annual_paise,
        "effective_date": str(rev.effective_date),
        "approved_at": rev.approved_at.isoformat() if rev.approved_at else None,
        "remarks": rev.remarks,
    }, "Compensation revision approved successfully")


# POST /api/v2/payroll/compensation/revisions/{revisionId}/reject
@router.post("/compensation/revisions/{revisionId}/reject", summary="Reject compensation revision")
async def reject_compensation_revision(
    revisionId: uuid.UUID,
    payload: CompensationRevisionRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    rev = await CompensationService.reject_revision(
        session=db,
        revision_id=revisionId,
        user_id=user_id,
        user_role=user_role,
        reason=payload.reason,
    )
    return _ok({
        "id": str(rev.id),
        "employee_id": str(rev.employee_id),
        "status": rev.status,
        "rejected_at": rev.rejected_at.isoformat() if rev.rejected_at else None,
        "rejection_reason": rev.rejection_reason,
    }, "Compensation revision rejected successfully")
