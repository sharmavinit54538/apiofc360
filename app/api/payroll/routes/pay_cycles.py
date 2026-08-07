"""FastAPI Route Handlers for Enterprise Payroll Cycle Management — Database Persisted, Locks & Audit Logged."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.payroll_cycle import (
    PayCycleSchema,
    PayCycleCreateSchema,
    PayCycleUpdateSchema,
    PayCycleLockSchema,
    PayCycleActionSchema,
)
from app.services.pay_cycle_full_service import PayCycleFullService

router = APIRouter()


def _cycle_to_dict(c) -> dict:
    """Helper to convert PayCycle model to dictionary."""
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "name": c.name or "Monthly Payroll Cycle",
        "frequency": c.frequency or "MONTHLY",
        "period_month": c.period_month,
        "period_year": c.period_year,
        "status": c.status or "DRAFT",
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "processing_date": c.processing_date.isoformat() if c.processing_date else None,
        "payment_date": c.payment_date.isoformat() if c.payment_date else None,
        "payslip_generation_date": c.payslip_generation_date.isoformat() if c.payslip_generation_date else None,
        "attendance_lock_date": c.attendance_lock_date.isoformat() if c.attendance_lock_date else None,
        "leave_lock_date": c.leave_lock_date.isoformat() if c.leave_lock_date else None,
        "overtime_lock_date": c.overtime_lock_date.isoformat() if c.overtime_lock_date else None,
        "tax_calculation_date": c.tax_calculation_date.isoformat() if c.tax_calculation_date else None,
        "bonus_processing_date": c.bonus_processing_date.isoformat() if c.bonus_processing_date else None,
        "is_active": c.is_active,
        "is_locked": c.is_locked,
        "locks": c.locks or {
            "attendance": False, "leaves": False, "overtime": False,
            "components": False, "tax": False, "payslips": False
        },
        "automation": c.automation or {
            "auto_generation": True, "auto_payslip": True, "auto_calc": True,
            "auto_email": True, "auto_whatsapp": False, "auto_rollover": True
        },
        "total_employees": c.total_employees or 0,
        "total_gross": float(c.total_gross or 0.0),
        "total_deductions": float(c.total_deductions or 0.0),
        "total_net": float(c.total_net or 0.0),
        "remarks": c.remarks or "",
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/cycles", response_model=APIResponse[dict], summary="List all payroll cycles")
@router.head("/cycles")
async def list_payroll_cycles(
    status_filter: Optional[str] = Query(None, alias="status"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cycles = await PayCycleFullService.list_cycles(db, status_filter=status_filter)
    items = [_cycle_to_dict(c) for c in cycles]
    return success_response({"items": items, "total": len(items)}, "Payroll cycles retrieved successfully.")


@router.get("/cycles/logs", response_model=APIResponse[List[dict]], summary="Get payroll cycle audit logs")
async def get_payroll_cycle_logs(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayCycleFullService.get_logs(db)
    return success_response(logs, "Payroll cycle logs retrieved successfully.")


@router.get("/cycles/history", response_model=APIResponse[List[dict]], summary="Get payroll cycle history")
async def get_payroll_cycle_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayCycleFullService.get_logs(db)
    return success_response(logs, "Payroll cycle history retrieved successfully.")


@router.get("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Get single payroll cycle details")
async def get_payroll_cycle_details(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(cycle), "Payroll cycle details retrieved.")


@router.post("/cycles", status_code=201, response_model=APIResponse[dict], summary="Create new payroll cycle")
async def create_payroll_cycle(
    payload: PayCycleCreateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    created = await PayCycleFullService.create_cycle(
        db=db,
        data=payload.model_dump(),
        actor_email=actor_email,
        ip_address=ip_address,
        browser=browser
    )
    return success_response(_cycle_to_dict(created), "Payroll cycle created successfully.")


@router.put("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Update payroll cycle")
@router.patch("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Partial update payroll cycle")
async def update_payroll_cycle(
    cycle_id: uuid.UUID,
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    updated = await PayCycleFullService.update_cycle(
        db=db,
        cycle_id=cycle_id,
        payload=payload,
        actor_email=actor_email,
        ip_address=ip_address,
        browser=browser
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(updated), "Payroll cycle updated successfully.")


@router.delete("/cycles/{cycle_id}", response_model=APIResponse[dict], summary="Delete payroll cycle")
async def delete_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    deleted = await PayCycleFullService.delete_cycle(db, cycle_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response({"id": str(cycle_id)}, "Payroll cycle deleted successfully.")


@router.post("/cycles/{cycle_id}/activate", response_model=APIResponse[dict], summary="Activate payroll cycle")
async def activate_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    activated = await PayCycleFullService.activate_cycle(db, cycle_id, actor_email=actor_email)
    if not activated:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(activated), "Payroll cycle activated as primary active run.")


@router.post("/cycles/{cycle_id}/lock", response_model=APIResponse[dict], summary="Lock payroll cycle")
async def lock_payroll_cycle(
    cycle_id: uuid.UUID,
    payload: PayCycleLockSchema = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    locks_data = None
    if payload:
        dumped = payload.model_dump(exclude_unset=True)
        locks_data = {k.replace("lock_", ""): v for k, v in dumped.items() if k.startswith("lock_")}

    locked = await PayCycleFullService.toggle_lock(db, cycle_id, lock_state=True, locks_data=locks_data, actor_email=actor_email)
    if not locked:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(locked), "Payroll cycle locked successfully.")


@router.post("/cycles/{cycle_id}/unlock", response_model=APIResponse[dict], summary="Unlock payroll cycle")
async def unlock_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    unlocked = await PayCycleFullService.toggle_lock(db, cycle_id, lock_state=False, actor_email=actor_email)
    if not unlocked:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(unlocked), "Payroll cycle unlocked successfully.")


@router.post("/cycles/{cycle_id}/duplicate", response_model=APIResponse[dict], summary="Duplicate payroll cycle")
async def duplicate_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    duplicated = await PayCycleFullService.duplicate_cycle(db, cycle_id, actor_email=actor_email)
    if not duplicated:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(duplicated), "Payroll cycle duplicated for upcoming period.")


@router.post("/cycles/{cycle_id}/archive", response_model=APIResponse[dict], summary="Archive payroll cycle")
async def archive_payroll_cycle(
    cycle_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    archived = await PayCycleFullService.archive_cycle(db, cycle_id, actor_email=actor_email)
    if not archived:
        raise HTTPException(status_code=404, detail="Payroll cycle not found.")
    return success_response(_cycle_to_dict(archived), "Payroll cycle archived successfully.")


# Backward compatibility aliases
create_pay_cycle = create_payroll_cycle
get_pay_cycle = get_payroll_cycle_details
list_pay_cycles = list_payroll_cycles

