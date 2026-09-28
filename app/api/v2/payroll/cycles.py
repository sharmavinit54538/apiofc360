"""Payroll Cycles router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.cycles import PayrollCycleActionRequest
from app.services.payroll.cycle_service import PayrollCycleService

router = APIRouter(tags=["Payroll v2 - Cycles"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _cycle_dict(c) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "name": c.name,
        "frequency": c.frequency,
        "period_month": c.period_month,
        "period_year": c.period_year,
        "status": c.status,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "processing_date": str(c.processing_date) if c.processing_date else None,
        "payment_date": str(c.payment_date) if c.payment_date else None,
        "is_active": c.is_active,
        "is_locked": c.is_locked,
        "total_employees": c.total_employees,
        "total_gross": float(c.total_gross or 0),
        "total_deductions": float(c.total_deductions or 0),
        "total_net": float(c.total_net or 0),
        "remarks": c.remarks,
    }


# GET /api/v2/payroll/cycles
@router.get("/cycles", summary="List payroll cycles")
async def list_payroll_cycles(
    status: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    cycles = await PayrollCycleService.list_cycles(db, company_id=c_uuid, status_filter=status)
    return _ok([_cycle_dict(c) for c in cycles], "Payroll cycles retrieved successfully")


# GET /api/v2/payroll/cycles/{cycleId}
@router.get("/cycles/{cycleId}", summary="Get payroll cycle details")
async def get_payroll_cycle(
    cycleId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cycle = await PayrollCycleService.get_cycle(db, cycleId)
    return _ok(_cycle_dict(cycle), "Payroll cycle retrieved successfully")


# POST /api/v2/payroll/cycles/{cycleId}/reopen
@router.post("/cycles/{cycleId}/reopen", summary="Reopen a payroll cycle")
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
    return _ok(_cycle_dict(cycle), f"Payroll cycle '{cycle.name}' reopened successfully")


# POST /api/v2/payroll/cycles/{cycleId}/void
@router.post("/cycles/{cycleId}/void", summary="Void a payroll cycle")
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
    return _ok(_cycle_dict(cycle), f"Payroll cycle '{cycle.name}' marked as VOID")
