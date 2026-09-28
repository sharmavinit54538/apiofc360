"""Full & Final Settlement router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.full_and_final import (
    FullAndFinalApproveRequest,
    FullAndFinalCreateRequest,
    FullAndFinalFinalizeRequest,
    FullAndFinalRejectRequest,
)
from app.services.payroll.full_and_final_service import FullAndFinalService

router = APIRouter(tags=["Payroll v2 - Full and Final"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _fnf_dict(item) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "employee_id": str(item.employee_id),
        "company_id": str(item.company_id) if item.company_id else None,
        "resignation_date": str(item.resignation_date),
        "last_working_date": str(item.last_working_date),
        "exit_type": item.exit_type,
        "reason": item.reason,
        "notice_period_days_required": item.notice_period_days_required,
        "notice_period_days_served": item.notice_period_days_served,
        "shortfall_days": item.shortfall_days,
        "status": item.status,
        "net_payable_paise": item.net_payable_paise,
        "remarks": item.remarks,
        "notes": item.notes,
        "statement_path": item.statement_path,
        "approved_by": str(item.approved_by) if item.approved_by else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "finalized_by": str(item.finalized_by) if item.finalized_by else None,
        "finalized_at": item.finalized_at.isoformat() if item.finalized_at else None,
        "rejected_by": str(item.rejected_by) if item.rejected_by else None,
        "rejected_at": item.rejected_at.isoformat() if item.rejected_at else None,
        "rejection_reason": item.rejection_reason,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


# GET /api/v2/payroll/full-and-final
@router.get("/full-and-final", summary="List full and final settlements")
async def list_full_and_final(
    status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await FullAndFinalService.list_settlements(
        session=db,
        company_id=c_uuid,
        status_filter=status,
        department=department,
        search=search,
        page=page,
        limit=limit,
    )
    items = [_fnf_dict(i) for i in res["items"]]
    return _ok({
        "items": items,
        "total": res["total"],
        "page": res["page"],
        "limit": res["limit"],
    }, "Full and final settlements retrieved successfully")


# POST /api/v2/payroll/full-and-final
@router.post("/full-and-final", status_code=status.HTTP_201_CREATED, summary="Initiate full and final settlement")
async def create_full_and_final(
    payload: FullAndFinalCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    emp_uuid = uuid.UUID(payload.employee_id)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    settlement = await FullAndFinalService.create_settlement(
        session=db,
        employee_id=emp_uuid,
        exit_details=payload.exit_details,
        remarks=payload.remarks,
        user_id=user_id,
        user_role=user_role,
        company_id=c_uuid,
    )
    return _ok(_fnf_dict(settlement), "Full and final settlement initiated successfully")


# GET /api/v2/payroll/full-and-final/{fnfId}
@router.get("/full-and-final/{fnfId}", summary="Get full and final settlement details")
async def get_full_and_final(
    fnfId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    settlement = await FullAndFinalService.get_settlement(db, fnfId)
    return _ok(_fnf_dict(settlement), "Full and final settlement details retrieved successfully")


# POST /api/v2/payroll/full-and-final/{fnfId}/approve
@router.post("/full-and-final/{fnfId}/approve", summary="Approve full and final settlement")
async def approve_full_and_final(
    fnfId: uuid.UUID,
    payload: Optional[FullAndFinalApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    remarks = payload.remarks if payload else None
    settlement = await FullAndFinalService.approve_settlement(
        session=db,
        fnf_id=fnfId,
        user_id=user_id,
        user_role=user_role,
        remarks=remarks,
    )
    return _ok(_fnf_dict(settlement), "Full and final settlement approved successfully")


# POST /api/v2/payroll/full-and-final/{fnfId}/finalize
@router.post("/full-and-final/{fnfId}/finalize", summary="Finalize full and final settlement")
async def finalize_full_and_final(
    fnfId: uuid.UUID,
    payload: Optional[FullAndFinalFinalizeRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    notes = payload.notes if payload else None
    settlement = await FullAndFinalService.finalize_settlement(
        session=db,
        fnf_id=fnfId,
        user_id=user_id,
        user_role=user_role,
        notes=notes,
    )
    return _ok(_fnf_dict(settlement), "Full and final settlement finalized successfully")


# POST /api/v2/payroll/full-and-final/{fnfId}/reject
@router.post("/full-and-final/{fnfId}/reject", summary="Reject full and final settlement")
async def reject_full_and_final(
    fnfId: uuid.UUID,
    payload: FullAndFinalRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    settlement = await FullAndFinalService.reject_settlement(
        session=db,
        fnf_id=fnfId,
        user_id=user_id,
        user_role=user_role,
        reason=payload.reason,
    )
    return _ok(_fnf_dict(settlement), "Full and final settlement rejected")


# GET /api/v2/payroll/full-and-final/{fnfId}/statement/download
@router.get("/full-and-final/{fnfId}/statement/download", summary="Download full and final settlement statement")
async def download_full_and_final_statement(
    fnfId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    content_bytes, filename = await FullAndFinalService.generate_statement(db, fnf_id=fnfId)
    return Response(
        content=content_bytes,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
