"""Employee Health router for OFC360 / Aurix HRMS Core Modules (Sensitive Medical Data)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.core_modules.attendance_service import AttendanceCoreService
from app.services.core_modules.compliance_health_service import EmployeeHealthService

router = APIRouter(prefix="/employee-health", tags=["Core - Employee Health"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("")
@router.get("/")
async def get_health_overview(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = EmployeeHealthService(session)
    res = await srv.get_analytics(cid)
    return _ok(res)


@router.get("/profile")
async def get_my_health_profile(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    att_srv = AttendanceCoreService(session)
    emp = await att_srv.get_employee_by_user_id(uid)
    emp_id = emp.id if emp else uid
    srv = EmployeeHealthService(session)
    profile = await srv.get_profile(emp_id)
    return _ok(profile)


@router.get("/records")
async def list_health_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    att_srv = AttendanceCoreService(session)
    emp = await att_srv.get_employee_by_user_id(uid)
    emp_id = emp.id if emp else uid
    srv = EmployeeHealthService(session)
    res = await srv.list_records(employee_id=emp_id, page=page, limit=limit)
    return _ok(res)


@router.get("/analytics")
async def get_health_analytics(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = EmployeeHealthService(session)
    res = await srv.get_analytics(cid)
    return _ok(res)
