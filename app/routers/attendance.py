"""Attendance router for OFC360 / Aurix HRMS Core Modules.

Note: Face biometric check-in/check-out endpoints have been moved to
/app/attendance/routers/ for real biometric verification with liveness detection.
This router provides non-biometric attendance operations only.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

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
)
from app.services.core_modules.attendance_service import AttendanceCoreService

router = APIRouter(prefix="/attendance", tags=["Core - Attendance"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> uuid.UUID | None:
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
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
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
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    status: str | None = Query(None),
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
    target_date: date | None = Query(None),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.get_analytics(company_id=cid, target_date=target_date)
    return _ok(res)


@router.get("/analytics/trends")
async def get_attendance_analytics_trends(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.get_analytics_trends(company_id=cid, from_date=from_date, to_date=to_date)
    return _ok(res)


@router.get("/analytics/rate")
async def get_attendance_analytics_rate(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.get_analytics_rate(company_id=cid, from_date=from_date, to_date=to_date)
    return _ok(res)


@router.get("/analytics/weekly")
async def get_attendance_analytics_weekly(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    weeks: int = Query(4, ge=1, le=12),
):
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.get_analytics_weekly(company_id=cid, weeks=weeks)
    return _ok(res)


@router.get("/calendar")
async def get_attendance_calendar(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    month: int = Query(9, ge=1, le=12),
    year: int = Query(2026, ge=2000, le=2100),
):
    cid = _get_cid(claims)
    if not cid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company context required")
    srv = AttendanceCoreService(session)
    cal = await srv.get_calendar(company_id=cid, month=month, year=year)
    return _ok(cal)


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
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    res = await srv.list_records(company_id=cid, from_date=from_date, to_date=to_date, page=1, limit=10000)
    
    # Generate CSV
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee ID", "Date", "Check In", "Check Out", "Status", 
        "Is Late", "Late Minutes", "Working Hours", "Notes"
    ])
    for item in res["items"]:
        writer.writerow([
            item["employee_id"],
            item["date"],
            item["check_in_time"] or "",
            item["check_out_time"] or "",
            item["status"],
            "Yes" if item["is_late"] else "No",
            item["late_minutes"],
            item["working_hours"],
            item["notes"] or "",
        ])
    
    output.seek(0)
    filename = f"attendance_export_{date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    record = await srv.update_attendance(attendance_id, payload, editor_id=uid, requester_company_id=cid)
    return _ok({"id": str(record.id), "updated": True, "notes": record.notes})


@router.delete("/{attendance_id}")
async def delete_attendance_record(
    attendance_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = AttendanceCoreService(session)
    deleted = await srv.delete_attendance(attendance_id, requester_company_id=cid)
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
    _uid(claims)
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
