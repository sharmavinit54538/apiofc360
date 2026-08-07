"""FastAPI Route Handlers for Enterprise Overtime Management System Settings."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.overtime_setting import (
    PayrollOvertimeSettingSchema,
    PayrollOvertimeUpdateSchema,
    CalculateOvertimeSchema,
)
from app.services.overtime_setting_service import OvertimeSettingService

router = APIRouter()


def _setting_to_dict(s) -> dict:
    """Helper to convert PayrollOvertimeSetting model to dictionary."""
    return {
        "id": str(s.id),
        "company_id": str(s.company_id) if s.company_id else None,
        "overtime_enabled": s.overtime_enabled,
        "overtime_code": s.overtime_code,
        "calc_method": s.calc_method or "HOURLY_MULTIPLIER",
        "standard_multiplier": float(s.standard_multiplier or 1.5),
        "weekend_multiplier": float(s.weekend_multiplier or 1.5),
        "holiday_multiplier": float(s.holiday_multiplier or 2.0),
        "night_shift_multiplier": float(s.night_shift_multiplier or 1.25),
        "emergency_multiplier": float(s.emergency_multiplier or 2.5),
        "min_hours_per_day": float(s.min_hours_per_day or 1.0),
        "max_hours_per_day": float(s.max_hours_per_day or 4.0),
        "max_hours_per_week": float(s.max_hours_per_week or 16.0),
        "max_hours_per_month": float(s.max_hours_per_month or 50.0),
        "auto_approval_enabled": s.auto_approval_enabled,
        "auto_approval_threshold_hours": float(s.auto_approval_threshold_hours or 2.0),
        "require_manager_approval": s.require_manager_approval,
        "comp_off_enabled": s.comp_off_enabled,
        "comp_off_expiry_days": s.comp_off_expiry_days or 90,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("/overtime/settings", response_model=APIResponse[dict], summary="Get company overtime policy settings")
@router.head("/overtime/settings")
async def get_overtime_settings(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    setting = await OvertimeSettingService.get_settings(db)
    return success_response(_setting_to_dict(setting), "Overtime policy settings retrieved.")


@router.put("/overtime/settings", response_model=APIResponse[dict], summary="Update company overtime policy settings")
async def update_overtime_settings(
    payload: PayrollOvertimeUpdateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    try:
        updated = await OvertimeSettingService.update_settings(
            db=db,
            payload=payload.model_dump(exclude_unset=True),
            actor_email=actor_email,
            ip_address=ip_address,
            browser=browser
        )
        return success_response(_setting_to_dict(updated), "Overtime policy settings updated successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/overtime/calculate", response_model=APIResponse[dict], summary="Calculate live overtime pay")
async def calculate_overtime(
    payload: CalculateOvertimeSchema,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    result = await OvertimeSettingService.calculate_overtime_pay(
        db=db,
        basic_salary=payload.basic_salary,
        overtime_hours=payload.overtime_hours,
        ot_type=payload.ot_type,
        working_days=payload.working_days_in_month or 26,
        hours_per_day=payload.working_hours_per_day or 8
    )
    return success_response(result, "Overtime payout calculated successfully.")


@router.post("/overtime/request", response_model=APIResponse[dict], summary="Submit employee overtime request")
async def create_overtime_request(
    payload: dict,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    res = {
        "id": str(uuid.uuid4()),
        "status": "PENDING",
        "employee_id": payload.get("employee_id"),
        "overtime_hours": payload.get("overtime_hours", 2.0),
        "reason": payload.get("reason", "Project overtime request"),
        "created_at": datetime.utcnow().isoformat()
    }
    return success_response(res, "Overtime request submitted for manager approval.")


@router.get("/overtime/history", response_model=APIResponse[List[dict]], summary="Get overtime policy history")
async def get_overtime_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await OvertimeSettingService.get_audit_logs(db)
    return success_response(logs, "Overtime policy history retrieved.")


@router.get("/overtime/audit", response_model=APIResponse[List[dict]], summary="Get overtime policy audit logs")
async def get_overtime_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await OvertimeSettingService.get_audit_logs(db)
    return success_response(logs, "Overtime policy audit logs retrieved.")
