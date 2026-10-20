"""Payroll Cycles router for Payroll v2 (operates on canonical PayrollPeriod)."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.cycles import PayrollCycleActionRequest, PayrollCycleCreateRequest
from app.schemas.payroll_v2.periods import PayrollPeriodResponse
from app.services.payroll.cycle_service import PayrollCycleService

router = APIRouter(tags=["Payroll v2 - Cycles"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _period_dict(p) -> dict[str, Any]:
    """Convert PayrollPeriod to dict matching frontend expectations."""
    return {
        "id": str(p.id),
        "company_id": str(p.company_id) if p.company_id else None,
        "name": p.name,
        "frequency": "MONTHLY",  # Fixed for now
        "period_month": p.period_month,
        "period_year": p.period_year,
        "status": p.status,
        "start_date": str(p.start_date) if p.start_date else None,
        "end_date": str(p.end_date) if p.end_date else None,
        "processing_date": str(p.processing_date) if p.processing_date else None,
        "payment_date": str(p.payment_date) if p.payment_date else None,
        "pay_date": str(p.pay_date) if p.pay_date else None,
        "is_locked": p.is_locked,
        "remarks": p.remarks,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# GET /api/v2/payroll/cycles
@router.get("/cycles", summary="List payroll periods")
async def list_payroll_cycles(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await PayrollCycleService.list_cycles(db, company_id=c_uuid, status_filter=status, page=page, page_size=page_size)
    items = [_period_dict(c) for c in res["items"]]
    return _ok({"items": items, "total": res["total"], "page": res["page"], "page_size": res["page_size"]}, "Payroll periods retrieved successfully")


# POST /api/v2/payroll/cycles
@router.post("/cycles", status_code=status.HTTP_201_CREATED, summary="Create new payroll period")
async def create_payroll_cycle(
    payload: PayrollCycleCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    user_id = _uid(claims)
    user_role = _role(claims)
    cycle = await PayrollCycleService.create_cycle(
        session=db,
        company_id=c_uuid,
        name=payload.name,
        frequency=payload.frequency,
        period_month=payload.period_month,
        period_year=payload.period_year,
        start_date=payload.start_date,
        end_date=payload.end_date,
        processing_date=payload.processing_date,
        payment_date=payload.payment_date,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_period_dict(cycle), "Payroll period created successfully")


# GET /api/v2/payroll/cycles/{cycleId}
@router.get("/cycles/{cycleId}", summary="Get payroll period details")
async def get_payroll_cycle(
    cycleId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cycle = await PayrollCycleService.get_cycle(db, cycleId)
    return _ok(_period_dict(cycle), "Payroll period retrieved successfully")


# POST /api/v2/payroll/cycles/{cycleId}/lock
@router.post("/cycles/{cycleId}/lock", summary="Lock a payroll period")
async def lock_payroll_cycle(
    cycleId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    cycle = await PayrollCycleService.lock_cycle(
        session=db,
        cycle_id=cycleId,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_period_dict(cycle), f"Payroll period '{cycle.name}' locked successfully")


# POST /api/v2/payroll/cycles/{cycleId}/reopen
@router.post("/cycles/{cycleId}/reopen", summary="Reopen a payroll period")
async def reopen_payroll_cycle(
    cycleId: uuid.UUID,
    payload: PayrollCycleActionRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    cycle = await PayrollCycleService.reopen_cycle(
        session=db,
        cycle_id=cycleId,
        reason=payload.reason,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_period_dict(cycle), f"Payroll period '{cycle.name}' reopened successfully")


# POST /api/v2/payroll/cycles/{cycleId}/void
@router.post("/cycles/{cycleId}/void", summary="Void a payroll period")
async def void_payroll_cycle(
    cycleId: uuid.UUID,
    payload: PayrollCycleActionRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    cycle = await PayrollCycleService.void_cycle(
        session=db,
        cycle_id=cycleId,
        reason=payload.reason,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_period_dict(cycle), f"Payroll period '{cycle.name}' marked as VOID")
