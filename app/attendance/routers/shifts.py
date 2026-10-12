"""Shift Management API Routes."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.shift import (
    AssignedEmployeesListResponse,
    RosterEntryCreate,
    RosterEntryResponse,
    RosterEntryUpdate,
    RosterListResponse,
    ScheduleToday,
    ScheduleUpcoming,
    ScheduleHistory,
    SelfScheduleResponse,
    ShiftAssignRequest,
    ShiftAssignResponse,
    ShiftChangeRejectRequest,
    ShiftChangeRequestAction,
    ShiftChangeRequestCreate,
    ShiftChangeRequestListResponse,
    ShiftChangeRequestResponse,
    ShiftCreate,
    ShiftListResponse,
    ShiftMinimalResponse,
    ShiftResponse,
    ShiftUpdate,
)
from app.attendance.services.roster_service import RosterService
from app.attendance.services.shift_management_service import ShiftManagementService
from app.core.config import settings
from app.core.rbac import require_admin_or_manager, require_hr_admin
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse

router = APIRouter()

# Static routes MUST come before /{shift_id} to avoid path capture


@router.get(
    "/shifts/options",
    response_model=APIResponse[List[ShiftMinimalResponse]],
    summary="Get active shifts for dropdown (any authenticated employee)",
)
async def get_shifts_options(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    shifts = await service.get_active_shifts_options(company_id)
    return APIResponse(
        success=True,
        message="Active shifts retrieved.",
        data=[ShiftMinimalResponse.model_validate(s) for s in shifts],
    )


@router.get(
    "/shifts",
    response_model=APIResponse[ShiftListResponse],
    summary="List shifts with pagination and filters (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def list_shifts(
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    night_shift: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    shifts, total = await service.list_shifts(
        company_id, search=search, is_active=is_active, night_shift=night_shift, page=page, limit=limit
    )
    return APIResponse(
        success=True,
        message="Shifts retrieved.",
        data=ShiftListResponse(
            items=[ShiftResponse.model_validate(s) for s in shifts],
            total=total,
            page=page,
            limit=limit,
        ),
    )


@router.post(
    "/shifts",
    response_model=APIResponse[ShiftResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new shift (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def create_shift(
    body: ShiftCreate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    user_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    try:
        shift = await service.create_shift(
            company_id=company_id,
            created_by=user_id,
            name=body.name,
            code=body.code,
            start_time=body.start_time,
            end_time=body.end_time,
            grace_period_minutes=body.grace_period_minutes,
            break_duration_minutes=body.break_duration_minutes,
            is_night_shift=body.is_night_shift,
            night_premium_percent=body.night_premium_percent,
            working_days=body.working_days,
            is_active=body.is_active,
            is_default=body.is_default,
            color=body.color,
            description=body.description,
        )
    except ValueError as e:
        if str(e) == "DUPLICATE_SHIFT_NAME":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_SHIFT_NAME", "message": "A shift with this name already exists."},
            )
        if str(e) == "DUPLICATE_SHIFT_CODE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_SHIFT_CODE", "message": "A shift with this code already exists."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_DATA", "message": str(e)})

    return APIResponse(
        success=True,
        message="Shift created.",
        data=ShiftResponse.model_validate(shift),
    )


@router.get(
    "/shifts/{shift_id}",
    response_model=APIResponse[ShiftResponse],
    summary="Get shift by ID (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_shift(
    shift_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    shift = await service.get_shift(shift_id, company_id)
    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SHIFT_NOT_FOUND", "message": "Shift not found."},
        )
    return APIResponse(
        success=True,
        message="Shift retrieved.",
        data=ShiftResponse.model_validate(shift),
    )


@router.put(
    "/shifts/{shift_id}",
    response_model=APIResponse[ShiftResponse],
    summary="Update shift (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def update_shift(
    shift_id: uuid.UUID,
    body: ShiftUpdate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    try:
        shift = await service.update_shift(
            shift_id=shift_id,
            company_id=company_id,
            **body.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SHIFT_NOT_FOUND", "message": "Shift not found."},
            )
        if str(e) == "DUPLICATE_SHIFT_NAME":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_SHIFT_NAME", "message": "A shift with this name already exists."},
            )
        if str(e) == "DUPLICATE_SHIFT_CODE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_SHIFT_CODE", "message": "A shift with this code already exists."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_DATA", "message": str(e)})

    return APIResponse(
        success=True,
        message="Shift updated.",
        data=ShiftResponse.model_validate(shift),
    )


@router.delete(
    "/shifts/{shift_id}",
    response_model=APIResponse[dict],
    summary="Soft delete shift (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def delete_shift(
    shift_id: uuid.UUID,
    reassign_to: Optional[uuid.UUID] = Query(None),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    try:
        result = await service.delete_shift(shift_id, company_id, reassign_to)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SHIFT_NOT_FOUND", "message": "Shift not found."},
            )
        if "default shift" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "SHIFT_IS_DEFAULT", "message": "Cannot delete default shift."},
            )
        if "reassign" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "SHIFT_HAS_ASSIGNMENTS", "message": str(e)},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Shift deleted.",
        data=result,
    )


@router.post(
    "/shifts/{shift_id}/assign",
    response_model=APIResponse[ShiftAssignResponse],
    summary="Assign shift to employees (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def assign_shift(
    shift_id: uuid.UUID,
    body: ShiftAssignRequest,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    user_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    try:
        result = await service.assign_shift(
            company_id=company_id,
            shift_id=shift_id,
            employee_ids=body.employee_ids,
            effective_date=body.effective_date,
            assigned_by=user_id,
            notes=body.notes,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SHIFT_NOT_FOUND", "message": "Shift not found."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    # Check for invalid employees
    invalid_ids = [s["employee_id"] for s in result["skipped"] if s["reason"] == "INVALID_EMPLOYEE"]
    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_EMPLOYEES",
                "message": "Some employees are not valid for this company.",
                "data": {"employee_ids": [str(id) for id in invalid_ids]},
            },
        )

    return APIResponse(
        success=True,
        message=f"Assigned {result['assigned_count']} employees.",
        data=ShiftAssignResponse(**result),
    )


@router.get(
    "/shifts/{shift_id}/employees",
    response_model=APIResponse[AssignedEmployeesListResponse],
    summary="Get current assignees of a shift (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_shift_employees(
    shift_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    assignments, total = await service.get_assigned_employees(shift_id, company_id, page, limit)

    # Enrich with employee details
    items = []
    for a in assignments:
        emp_stmt = select(Employee).where(Employee.id == a.employee_id)
        emp_result = await db.execute(emp_stmt)
        emp = emp_result.scalars().first()
        if emp:
            items.append(AssignedEmployeeResponse(
                id=a.id,
                employee_id=emp.employee_id,
                first_name=emp.first_name,
                last_name=emp.last_name,
                department=emp.department,
                designation=emp.designation,
                branch=emp.branch,
                effective_from=a.effective_from,
                effective_to=a.effective_to,
            ))

    return APIResponse(
        success=True,
        message="Assigned employees retrieved.",
        data=AssignedEmployeesListResponse(items=items, total=total, page=page, limit=limit),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Self Schedule
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/shifts/me/schedule",
    response_model=APIResponse[SelfScheduleResponse],
    summary="Get my shift schedule (any authenticated employee)",
)
async def get_my_schedule(
    days_ahead: int = Query(14, ge=1, le=60),
    history_days: int = Query(30, ge=1, le=90),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    from app.attendance.services.shift_service import ShiftService
    from app.attendance.utils.timezone import get_company_tz, company_today

    company_id = uuid.UUID(claims["company_id"])
    user_id = uuid.UUID(claims["sub"])

    # Get employee
    from app.attendance.repositories.attendance_repository import AttendanceRepository
    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)
    if not employee or employee.company_id != company_id:
        raise HTTPException(status_code=404, detail="Employee not found.")

    tz = await get_company_tz(db, str(company_id))
    today = company_today(tz)

    shift_service = ShiftService(db)

    # Current shift
    current_resolved = await shift_service.resolve_for_date(employee, today, tz)
    current_shift = None
    if current_resolved.shift_id:
        current_shift = {
            "id": current_resolved.shift_id,
            "name": current_resolved.shift_name,
            "code": None,  # would need to fetch
            "start_time": current_resolved.start_dt.strftime("%H:%M"),
            "end_time": current_resolved.end_dt.strftime("%H:%M"),
            "is_overnight": current_resolved.is_overnight,
            "source": current_resolved.source,
        }

    # Today
    today_record = await repo.get_record_by_date(employee.id, today)
    today_sched = None
    if current_resolved:
        today_sched = ScheduleToday(
            date=today,
            day=today.strftime("%A"),
            shift_name=current_resolved.shift_name,
            start_time=current_resolved.start_dt.strftime("%H:%M"),
            end_time=current_resolved.end_dt.strftime("%H:%M"),
            is_overnight=current_resolved.is_overnight,
            is_off=current_resolved.is_off,
            is_holiday=current_resolved.is_holiday,
            holiday_name=current_resolved.holiday_name,
            source=current_resolved.source,
            checked_in=today_record is not None and today_record.check_in_time is not None,
            checked_out=today_record is not None and today_record.check_out_time is not None,
            check_in_time=today_record.check_in_time if today_record else None,
            check_out_time=today_record.check_out_time if today_record else None,
            working_hours=today_record.working_hours if today_record else None,
            is_late=today_record.is_late or False if today_record else False,
            late_minutes=today_record.late_minutes or 0 if today_record else 0,
        )

    # Upcoming
    end_date = today + timedelta(days=days_ahead)
    upcoming_resolved = await shift_service.resolve_range(employee, today + timedelta(days=1), end_date, tz)
    upcoming = []
    for r in upcoming_resolved:
        upcoming.append(ScheduleUpcoming(
            date=r.business_date,
            day=r.business_date.strftime("%A"),
            shift_name=r.shift_name,
            start_time=r.start_dt.strftime("%H:%M"),
            end_time=r.end_dt.strftime("%H:%M"),
            is_overnight=r.is_overnight,
            is_off=r.is_off,
            is_holiday=r.is_holiday,
            holiday_name=r.holiday_name,
            source=r.source,
            working_hours=r.scheduled_net_hours,
        ))

    # History
    history_start = today - timedelta(days=history_days)
    history_resolved = await shift_service.resolve_range(employee, history_start, today - timedelta(days=1), tz)

    # Fetch attendance records for the period
    from app.attendance.repositories.history_repository import AttendanceHistoryRepository
    history_repo = AttendanceHistoryRepository(db)
    history_records, _ = await history_repo.get_own_history(
        employee.id, page=1, limit=history_days + 10, start_date=history_start, end_date=today - timedelta(days=1)
    )
    record_map = {r.date: r for r in history_records}

    # Get holidays and leaves for status
    from app.models.calendar.holiday import HolidayCalendar
    from sqlalchemy import select
    holiday_stmt = select(HolidayCalendar).where(
        and_(
            HolidayCalendar.company_id == company_id,
            HolidayCalendar.holiday_date >= history_start,
            HolidayCalendar.holiday_date <= today,
        )
    )
    if employee.branch:
        holiday_stmt = holiday_stmt.where(
            or_(HolidayCalendar.branch.is_(None), HolidayCalendar.branch == employee.branch)
        )
    holiday_result = await db.execute(holiday_stmt)
    holidays = {h.holiday_date: h.holiday_name for h in holiday_result.scalars().all()}

    history = []
    for r in history_resolved:
        record = record_map.get(r.business_date)
        is_off = r.is_off
        is_holiday = r.is_holiday
        status_str = "Absent"
        if is_holiday:
            status_str = "Holiday"
        elif r.off_reason == "leave":
            status_str = "On Leave"
        elif r.off_reason == "weekly_off":
            status_str = "Off"
        elif r.off_reason == "roster_off":
            status_str = "Off"
        elif record:
            if record.auto_closed:
                status_str = "Auto Closed"
            elif record.is_late:
                status_str = "Late"
            elif record.check_out_time:
                status_str = "Present"
            else:
                status_str = "Present"

        history.append(ScheduleHistory(
            attendance_id=record.id if record else None,
            date=r.business_date,
            day=r.business_date.strftime("%A"),
            shift_name=r.shift_name,
            scheduled_start=r.start_dt.strftime("%H:%M") if r.start_dt else None,
            scheduled_end=r.end_dt.strftime("%H:%M") if r.end_dt else None,
            check_in_time=record.check_in_time if record else None,
            check_out_time=record.check_out_time if record else None,
            working_hours=record.working_hours if record else None,
            overtime_hours=record.overtime_hours or 0.0 if record else 0.0,
            status=status_str,
            is_late=record.is_late or False if record else False,
            late_minutes=record.late_minutes or 0 if record else 0,
            is_early_checkout=record.is_early_checkout if record else False,
            early_minutes=record.early_minutes or 0 if record else 0,
            auto_closed=record.auto_closed if record else False,
        ))

    # Employee info
    employee_info = {
        "id": employee.id,
        "employee_id": employee.employee_id,
        "full_name": f"{employee.first_name} {employee.last_name}",
        "department": employee.department,
        "designation": employee.designation,
        "branch": employee.branch,
    }

    has_assigned_shift = current_resolved.source != "fallback"

    return APIResponse(
        success=True,
        message="Schedule retrieved.",
        data=SelfScheduleResponse(
            has_assigned_shift=has_assigned_shift,
            timezone=str(tz),
            employee=employee_info,
            current_shift=current_shift,
            today=today_sched,
            upcoming=upcoming,
            history=history,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Change Requests
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/shifts/change-requests",
    response_model=APIResponse[ShiftChangeRequestResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create shift change request (employee)",
)
async def create_change_request(
    body: ShiftChangeRequestCreate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    from app.attendance.utils.timezone import company_today, get_company_tz

    company_id = uuid.UUID(claims["company_id"])
    employee_id = uuid.UUID(claims["sub"])

    tz = await get_company_tz(db, str(company_id))
    tomorrow = company_today(tz) + timedelta(days=1)

    if body.effective_date < tomorrow:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_EFFECTIVE_DATE", "message": "Effective date must be tomorrow or later."},
        )

    service = ShiftManagementService(db)
    try:
        request = await service.create_change_request(
            company_id=company_id,
            employee_id=employee_id,
            requested_shift_id=body.requested_shift_id,
            effective_date=body.effective_date,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": str(e)},
        )

    return APIResponse(
        success=True,
        message="Change request submitted.",
        data=ShiftChangeRequestResponse.model_validate(request),
    )


@router.get(
    "/shifts/change-requests/mine",
    response_model=APIResponse[ShiftChangeRequestListResponse],
    summary="Get my shift change requests (employee)",
)
async def get_my_change_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    employee_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    requests, total = await service.list_my_change_requests(employee_id, company_id, page, limit)
    return APIResponse(
        success=True,
        message="Change requests retrieved.",
        data=ShiftChangeRequestListResponse(
            items=[ShiftChangeRequestResponse.model_validate(r) for r in requests],
            total=total,
            page=page,
            limit=limit,
        ),
    )


@router.get(
    "/shifts/change-requests",
    response_model=APIResponse[ShiftChangeRequestListResponse],
    summary="List all shift change requests (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def list_change_requests(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = ShiftManagementService(db)
    requests, total = await service.list_change_requests(company_id, status, page, limit)
    return APIResponse(
        success=True,
        message="Change requests retrieved.",
        data=ShiftChangeRequestListResponse(
            items=[ShiftChangeRequestResponse.model_validate(r) for r in requests],
            total=total,
            page=page,
            limit=limit,
        ),
    )


@router.post(
    "/shifts/change-requests/{request_id}/approve",
    response_model=APIResponse[ShiftChangeRequestResponse],
    summary="Approve shift change request (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def approve_change_request(
    request_id: uuid.UUID,
    body: ShiftChangeRequestAction,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    user_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    try:
        request = await service.approve_change_request(request_id, company_id, user_id, body.note)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Change request not found."},
            )
        if "invalid state" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHANGE_REQUEST_INVALID_STATE", "message": "Request is not in pending state."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Change request approved.",
        data=ShiftChangeRequestResponse.model_validate(request),
    )


@router.post(
    "/shifts/change-requests/{request_id}/reject",
    response_model=APIResponse[ShiftChangeRequestResponse],
    summary="Reject shift change request (HR admin)",
    dependencies=[Depends(require_hr_admin)],
)
async def reject_change_request(
    request_id: uuid.UUID,
    body: ShiftChangeRejectRequest,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    user_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    try:
        request = await service.reject_change_request(request_id, company_id, user_id, body.note)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Change request not found."},
            )
        if "invalid state" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHANGE_REQUEST_INVALID_STATE", "message": "Request is not in pending state."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Change request rejected.",
        data=ShiftChangeRequestResponse.model_validate(request),
    )


@router.post(
    "/shifts/change-requests/{request_id}/cancel",
    response_model=APIResponse[ShiftChangeRequestResponse],
    summary="Cancel my shift change request (employee)",
)
async def cancel_change_request(
    request_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    employee_id = uuid.UUID(claims["sub"])
    service = ShiftManagementService(db)
    try:
        request = await service.cancel_change_request(request_id, employee_id)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Change request not found."},
            )
        if "invalid state" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHANGE_REQUEST_INVALID_STATE", "message": "Request is not in pending state."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Change request cancelled.",
        data=ShiftChangeRequestResponse.model_validate(request),
    )


# Need to import select for the employee query in get_shift_employees
from sqlalchemy import select