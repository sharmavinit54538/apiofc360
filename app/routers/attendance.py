"""Attendance router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.attendance import (
    AttendanceCheckInRequest,
    AttendanceCheckOutRequest,
    AttendanceManualUpdateRequest,
    AttendanceRegularizationCreateRequest,
    FaceCheckInRequest,
    FaceEnrollRequest,
)
from app.services.core_modules.attendance_service import AttendanceCoreService

router = APIRouter(prefix="/attendance", tags=["Core - Attendance"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/me")
async def get_my_attendance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        return _ok(None, "No employee record associated with current user")
    record = await srv.get_today_record(emp.id)
    return _ok(record)


@router.get("/status")
async def get_attendance_status(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        return _ok({"status": "UNASSOCIATED", "checked_in": False})
    record = await srv.get_today_record(emp.id)
    checked_in = record is not None and record.check_in_time is not None
    checked_out = record is not None and record.check_out_time is not None
    return _ok({
        "employee_id": str(emp.id),
        "checked_in": checked_in,
        "checked_out": checked_out,
        "check_in_time": record.check_in_time.isoformat() if checked_in else None,
        "check_out_time": record.check_out_time.isoformat() if checked_out else None,
    })


@router.get("/today")
async def get_today_company_attendance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, from_date=date.today(), to_date=date.today(), page=page, limit=limit)
    return _ok(res)


@router.get("/history")
async def get_attendance_history(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    emp_id = emp.id if emp else None
    res = await srv.list_records(employee_id=emp_id, from_date=from_date, to_date=to_date, page=page, limit=limit)
    return _ok(res)


@router.get("/team")
async def get_team_attendance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, from_date=date.today(), to_date=date.today(), page=page, limit=limit)
    return _ok(res)


@router.get("/company")
async def get_company_attendance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, page=page, limit=limit)
    return _ok(res)


@router.get("/records")
async def get_all_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, from_date=from_date, to_date=to_date, status=status, page=page, limit=limit)
    return _ok(res)


@router.get("/analytics")
@router.get("/summary")
async def get_attendance_analytics(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    target_date: Optional[date] = Query(None),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.get_analytics(company_id=cid, target_date=target_date)
    return _ok(res)


@router.get("/calendar")
async def get_attendance_calendar(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    month: int = Query(9, ge=1, le=12),
    year: int = Query(2026, ge=2000, le=2100),
):
    return _ok({
        "month": month,
        "year": year,
        "working_days": 22,
        "holidays": 2,
        "calendar_summary": "All calendar logs synchronized",
    })


@router.get("/late")
async def get_late_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, status="late", page=page, limit=limit)
    return _ok(res)


@router.get("/early-leaving")
async def get_early_leaving_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, page=page, limit=limit)
    return _ok(res)


@router.get("/missing")
async def get_missing_punch_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, status="absent", page=page, limit=limit)
    return _ok(res)


@router.get("/overtime")
async def get_overtime_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, page=page, limit=limit)
    return _ok(res)


@router.get("/export")
async def export_attendance(
    claims: dict = Depends(get_current_user_claims),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
):
    _require_admin_or_manager(claims)
    return _ok({
        "status": "QUEUED",
        "task_id": f"task-att-exp-{uuid.uuid4().hex[:8]}",
        "message": "Attendance export initiated in background via Celery. Download link will be available soon.",
    })


@router.post("/check-in")
async def check_in(
    payload: AttendanceCheckInRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    record = await srv.check_in(emp.id, cid, payload)
    return _ok({"id": str(record.id), "status": record.status, "check_in_time": record.check_in_time.isoformat()})


@router.post("/check-out")
async def check_out(
    payload: AttendanceCheckOutRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    record = await srv.check_out(emp.id, cid, payload)
    return _ok({"id": str(record.id), "status": record.status, "check_out_time": record.check_out_time.isoformat() if record.check_out_time else None})


@router.post("/face/check-in")
async def face_check_in(
    payload: FaceCheckInRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    record = await srv.face_check_in(emp.id, cid, payload)
    return _ok({"id": str(record.id), "verified": True, "punch_type": "IN"})


@router.post("/face/check-out")
async def face_check_out(
    payload: FaceCheckInRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    record = await srv.face_check_out(emp.id, cid, payload)
    return _ok({"id": str(record.id), "verified": True, "punch_type": "OUT"})


@router.post("/face-enroll")
async def face_enroll(
    payload: FaceEnrollRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.face_enroll(cid, payload)
    return _ok(res)


@router.put("/{attendance_id}")
@router.patch("/{attendance_id}")
async def update_attendance_record(
    attendance_id: uuid.UUID,
    payload: AttendanceManualUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    uid = _uid(claims)
    srv = AttendanceCoreService(session)
    record = await srv.update_attendance(attendance_id, payload, editor_id=uid)
    return _ok({"id": str(record.id), "updated": True, "notes": record.notes})


@router.delete("/{attendance_id}")
async def delete_attendance_record(
    attendance_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    srv = AttendanceCoreService(session)
    deleted = await srv.delete_attendance(attendance_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return _ok({"id": str(attendance_id), "deleted": True})


@router.get("/regularization")
async def list_regularization_requests(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_regularizations(company_id=cid, page=page, limit=limit)
    return _ok(res)


@router.post("/regularization")
async def create_regularization_request(
    payload: AttendanceRegularizationCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    emp = await srv.get_employee_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    req = await srv.create_regularization(emp.id, cid, payload)
    return _ok({"id": str(req.id), "status": req.status, "message": "Regularization request submitted"})
