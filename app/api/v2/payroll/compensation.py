"""Compensation router for Payroll v2."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
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


def _comp_detail(c) -> dict[str, Any]:
    currency = c.__dict__.get("currency", "INR")
    fx_rate = Decimal(str(c.__dict__.get("fx_rate_to_inr", Decimal("1"))))
    from app.services.payroll.global_payroll import convert_minor_units
    return {
        "id": str(c.id),
        "employee_id": str(c.employee_id),
        "company_id": str(c.company_id) if c.company_id else None,
        "ctc_annual_paise": c.ctc_annual_paise,
        "ctc_annual_inr": float(Decimal(c.ctc_annual_paise) / 100 * fx_rate),
        "ctc_annual_inr_paise": convert_minor_units(c.ctc_annual_paise, fx_rate),
        "basic_monthly_paise": c.basic_monthly_paise,
        "basic_monthly_inr": float(Decimal(c.basic_monthly_paise) / 100 * fx_rate),
        "basic_monthly_inr_paise": convert_minor_units(c.basic_monthly_paise, fx_rate),
        "hra_monthly_paise": c.hra_monthly_paise,
        "hra_monthly_inr": float(Decimal(c.hra_monthly_paise) / 100 * fx_rate),
        "hra_monthly_inr_paise": convert_minor_units(c.hra_monthly_paise, fx_rate),
        "special_allowance_monthly_paise": c.special_allowance_monthly_paise,
        "special_allowance_monthly_inr": float(Decimal(c.special_allowance_monthly_paise) / 100 * fx_rate),
        "special_allowance_monthly_inr_paise": convert_minor_units(c.special_allowance_monthly_paise, fx_rate),
        "currency": currency,
        "fx_rate_to_inr": str(fx_rate),
        "ctc_annual_major": c.ctc_annual_paise / 100.0,
        "basic_monthly_major": c.basic_monthly_paise / 100.0,
        "hra_monthly_major": c.hra_monthly_paise / 100.0,
        "special_allowance_monthly_major": c.special_allowance_monthly_paise / 100.0,
        "effective_date": str(c.effective_date),
        "status": c.status,
        "remarks": c.remarks,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# GET /api/v2/payroll/compensations/{employeeId}
@router.get("/compensations/{employeeId}", summary="Get active compensation for an employee")
async def get_employee_compensation(
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    comp = await CompensationService.get_employee_compensation(db, employee_id=employeeId)
    return _ok(_comp_detail(comp), "Employee compensation retrieved successfully")


class AssignCompensationRequest(BaseModel):
    ctc_annual_paise: int
    basic_monthly_paise: Optional[int] = None
    hra_monthly_paise: Optional[int] = None
    special_allowance_monthly_paise: Optional[int] = None
    effective_date: Optional[date] = None
    remarks: Optional[str] = None
    currency: Optional[str] = None
    fx_rate_to_inr: Optional[Decimal] = None


# PUT /api/v2/payroll/compensations/{employeeId}
@router.put("/compensations/{employeeId}", summary="Assign or update employee CTC structure")
async def update_employee_compensation(
    employeeId: uuid.UUID,
    payload: AssignCompensationRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    comp = await CompensationService.assign_or_update_compensation(
        session=db,
        employee_id=employeeId,
        ctc_annual_paise=payload.ctc_annual_paise,
        basic_monthly_paise=payload.basic_monthly_paise,
        hra_monthly_paise=payload.hra_monthly_paise,
        special_allowance_monthly_paise=payload.special_allowance_monthly_paise,
        effective_date=payload.effective_date,
        remarks=payload.remarks,
        currency=payload.currency,
        fx_rate_to_inr=payload.fx_rate_to_inr,
    )
    return _ok(_comp_detail(comp), "Employee compensation updated successfully")


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
    rev = await CompensationService.approve_compensation_revision(
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
    rev = await CompensationService.reject_compensation_revision(
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
