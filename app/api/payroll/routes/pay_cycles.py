"""FastAPI Route Handlers for Enterprise Payroll Period Management — Database Persisted, Locks & Audit Logged."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.models.payroll import PayrollAuditLog
from app.schemas.auth import APIResponse
from app.services.payroll.cycle_service import PayrollCycleService

router = APIRouter()


def _period_to_dict(p) -> dict:
    """Helper to convert PayrollPeriod model to dictionary."""
    return {
        "id": str(p.id),
        "company_id": str(p.company_id) if p.company_id else None,
        "name": p.name,
        "frequency": "MONTHLY",
        "period_month": p.period_month,
        "period_year": p.period_year,
        "status": p.status,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "processing_date": p.processing_date.isoformat() if p.processing_date else None,
        "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        "pay_date": p.pay_date.isoformat() if p.pay_date else None,
        "is_active": p.status not in ("VOID", "CLOSED"),
        "is_locked": p.is_locked,
        "total_employees": 0,
        "total_gross": 0.0,
        "total_deductions": 0.0,
        "total_net": 0.0,
        "remarks": p.remarks or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/cycles", response_model=APIResponse[dict], summary="List all payroll periods")
@router.head("/cycles")
async def list_payroll_cycles(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await PayrollCycleService.list_cycles(db, company_id=c_uuid, status_filter=status_filter, page=page, page_size=page_size)
    items = [_period_to_dict(c) for c in res["items"]]
    return success_response({"items": items, "total": res["total"], "page": res["page"], "page_size": res["page_size"]}, "Payroll periods retrieved successfully.")


@router.get("/cycles/logs", response_model=APIResponse[List[dict]], summary="Get payroll cycle audit logs")
async def get_payroll_cycle_logs(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollCycleService.get_logs(db)
    return success_response(logs, "Payroll period logs retrieved successfully.")


@router.get("/cycles/history", response_model=APIResponse[List[dict]], summary="Get payroll period history")
async def get_payroll_cycle_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollCycleService.get_logs(db)
    return success_response(logs, "Payroll period history retrieved successfully.")


@router.get("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Get single payroll period details")
async def get_payroll_cycle_details(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    period = await PayrollCycleService.get_cycle(db, cycle_id)
    return success_response(_period_to_dict(period), "Payroll period details retrieved.")


@router.post("/cycles", status_code=201, response_model=APIResponse[dict], summary="Create new payroll period")
async def create_payroll_cycle(
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    user_id = uuid.UUID(claims.get("sub")) if claims.get("sub") else None
    user_role = claims.get("role")

    created = await PayrollCycleService.create_cycle(
        session=db,
        company_id=c_uuid,
        name=payload.get("name", "New Payroll Period"),
        frequency=payload.get("frequency", "MONTHLY"),
        period_month=payload.get("period_month", 1),
        period_year=payload.get("period_year", 2026),
        start_date=date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None,
        end_date=date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
        processing_date=date.fromisoformat(payload["processing_date"]) if payload.get("processing_date") else None,
        payment_date=date.fromisoformat(payload["payment_date"]) if payload.get("payment_date") else None,
        user_id=user_id,
        user_role=user_role,
    )
    return success_response(_period_to_dict(created), "Payroll period created successfully.")


@router.put("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Update payroll period")
@router.patch("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Partial update payroll period")
async def update_payroll_cycle(
    cycle_id: uuid.UUID,
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    period = await PayrollCycleService.get_cycle(db, cycle_id)
    # Simple update - just update allowed fields
    for field in ["name", "remarks", "start_date", "end_date", "processing_date", "payment_date"]:
        if field in payload and payload[field] is not None:
            if field.endswith("_date"):
                setattr(period, field, date.fromisoformat(payload[field]))
            else:
                setattr(period, field, payload[field])
    period.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(period)
    return success_response(_period_to_dict(period), "Payroll period updated successfully.")


@router.delete("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Delete payroll period (only OPEN/DRAFT)")
async def delete_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    period = await PayrollCycleService.get_cycle(db, cycle_id)
    if period.status not in ("OPEN", "DRAFT"):
        raise HTTPException(status_code=400, detail="Only OPEN/DRAFT periods can be deleted.")
    await db.delete(period)
    await db.commit()
    return success_response({"id": str(cycle_id)}, "Payroll period deleted successfully.")


@router.post("/cycles/{cycle_id}/lock", response_model=APIResponse[dict], summary="Lock payroll period")
async def lock_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    user_id = uuid.UUID(claims.get("sub")) if claims.get("sub") else None
    user_role = claims.get("role")
    locked = await PayrollCycleService.lock_cycle(db, cycle_id, user_id=user_id, user_role=user_role)
    if not locked:
        raise HTTPException(status_code=404, detail="Payroll period not found.")
    return success_response(_period_to_dict(locked), "Payroll period locked successfully.")


@router.post("/cycles/{cycle_id}/unlock", response_model=APIResponse[dict], summary="Unlock payroll period (reopen)")
async def unlock_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    user_id = uuid.UUID(claims.get("sub")) if claims.get("sub") else None
    user_role = claims.get("role")
    # Reopen is the equivalent of unlock for PayrollPeriod
    payload = type('obj', (object,), {'reason': 'Unlocked by admin'})()
    unlocked = await PayrollCycleService.reopen_cycle(db, cycle_id, reason="Unlocked by admin", user_id=user_id, user_role=user_role)
    if not unlocked:
        raise HTTPException(status_code=404, detail="Payroll period not found.")
    return success_response(_period_to_dict(unlocked), "Payroll period unlocked successfully.")


@router.post("/cycles/{cycle_id}/void", response_model=APIResponse[dict], summary="Void payroll period")
async def void_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    user_id = uuid.UUID(claims.get("sub")) if claims.get("sub") else None
    user_role = claims.get("role")
    voided = await PayrollCycleService.void_cycle(db, cycle_id, reason="Voided by admin", user_id=user_id, user_role=user_role)
    if not voided:
        raise HTTPException(status_code=404, detail="Payroll period not found.")
    return success_response(_period_to_dict(voided), "Payroll period voided successfully.")


# Backward compatibility aliases
create_pay_cycle = create_payroll_cycle
get_pay_cycle = get_payroll_cycle_details
list_pay_cycles = list_payroll_cycles

