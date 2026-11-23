"""Daily Face Attendance current employee status router."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.db.base import Base
from app.middleware.auth import get_current_user_claims
from app.attendance.schemas.response import AttendanceTodayResponse
from app.attendance.services.history_service import AttendanceHistoryService
from app.models.employee import Employee
from app.models.shift import Shift
from app.models.shift_plan import (
    ShiftPlan,
    ShiftPlanEntry,
    ShiftPlanSource,
    ShiftPlanStatus,
    EntryApprovalStatus,
    ShiftType,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise HTTPException(status_code=403, detail="Company context missing")
    return uuid.UUID(company_id_str)


def _format_time(time_obj: Optional[time]) -> Optional[str]:
    if time_obj is None:
        return None
    return time_obj.strftime("%H:%M")


# ── Shift Schedule ────────────────────────────────────────────────────────────

class ShiftScheduleItem(BaseModel):
    date: date
    shift_name: str
    shift_type: str
    start_time: Optional[str]
    end_time: Optional[str]
    is_off: bool
    is_overnight: bool
    duration_hours: float


class ShiftScheduleResponse(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    current_shift: Optional[str]
    schedule: list[ShiftScheduleItem]


@router.get(
    "/shifts/me/schedule",
    status_code=status.HTTP_200_OK,
    response_model=dict,
    summary="Get authenticated employee's shift schedule",
)
async def get_my_shift_schedule(
    start_date: Optional[date] = Query(None, description="Start date (defaults to today)"),
    end_date: Optional[date] = Query(None, description="End date (defaults to start_date + 30 days)"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Get shift schedule for the authenticated employee with shift details."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    # Get employee
    emp_stmt = select(Employee).where(
        Employee.user_id == user_id,
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Default date range
    today = date.today()
    if start_date is None:
        start_date = today
    if end_date is None:
        end_date = start_date + timedelta(days=30)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Get roster entries for the employee
    stmt = (
        select(ShiftPlanEntry, ShiftPlan, Shift)
        .join(ShiftPlan, ShiftPlanEntry.plan_id == ShiftPlan.id)
        .outerjoin(Shift, ShiftPlanEntry.shift_id == Shift.id)
        .where(
            and_(
                ShiftPlanEntry.employee_id == employee.id,
                ShiftPlanEntry.shift_date >= start_date,
                ShiftPlanEntry.shift_date <= end_date,
                ShiftPlanEntry.company_id == company_id,
                ShiftPlanEntry.approval_status == EntryApprovalStatus.APPROVED,
                ShiftPlan.status == ShiftPlanStatus.PUBLISHED,
            )
        )
        .order_by(ShiftPlanEntry.shift_date)
    )
    result = await db.execute(stmt)
    rows = result.all()

    schedule = []
    for entry, plan, shift in rows:
        is_off = entry.shift_type.value in ("OFF", "WEEKLY_OFF", "HOLIDAY")
        shift_name = entry.shift_type.value
        start_time = _format_time(entry.start_time)
        end_time = _format_time(entry.end_time)
        is_overnight = False
        duration_hours = 0.0

        if shift:
            shift_name = shift.name
            start_time = _format_time(shift.start_time)
            end_time = _format_time(shift.end_time)
            is_overnight = shift.is_overnight
            if shift.start_time and shift.end_time:
                start_min = shift.start_time.hour * 60 + shift.start_time.minute
                end_min = shift.end_time.hour * 60 + shift.end_time.minute
                if end_min <= start_min:
                    end_min += 24 * 60
                duration_hours = round((end_min - start_min) / 60.0, 2)

        schedule.append(ShiftScheduleItem(
            date=entry.shift_date,
            shift_name=shift_name,
            shift_type=entry.shift_type.value,
            start_time=start_time,
            end_time=end_time,
            is_off=is_off,
            is_overnight=is_overnight,
            duration_hours=duration_hours,
        ))

    current_shift = employee.shift

    return {
        "success": True,
        "message": "Shift schedule retrieved successfully.",
        "data": ShiftScheduleResponse(
            employee_id=employee.id,
            employee_name=f"{employee.first_name} {employee.last_name}".strip(),
            current_shift=current_shift,
            schedule=schedule,
        ).model_dump(mode="json"),
        "error": None,
    }


# ── Shift Change Requests ────────────────────────────────────────────────────

class ShiftChangeRequestCreate(BaseModel):
    requested_shift_id: uuid.UUID = Field(description="ID of the shift to change to")
    start_date: date = Field(description="Start date for the change")
    end_date: date | None = Field(default=None, description="End date for the change (optional)")
    reason: str = Field(min_length=1, max_length=1000, description="Reason for shift change request")


class ShiftChangeRequestResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    current_shift: str | None
    requested_shift_id: uuid.UUID
    requested_shift_name: str
    start_date: date
    end_date: date | None
    reason: str
    status: str
    requested_at: datetime
    reviewed_at: datetime | None
    reviewed_by: uuid.UUID | None


class ShiftChangeRequest(BaseModel):
    """Shift change request model."""
    requested_shift_id: uuid.UUID = Field(description="ID of the shift to change to")
    start_date: date = Field(description="Start date for the change")
    end_date: date | None = Field(default=None, description="End date for the change (optional)")
    reason: str = Field(min_length=1, max_length=1000, description="Reason for shift change request")


@router.post(
    "/shifts/change-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
    summary="Submit shift change request",
)
async def create_shift_change_request(
    payload: ShiftChangeRequestCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Submit a shift change request for the authenticated employee."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    # Get employee
    emp_stmt = select(Employee).where(
        Employee.user_id == user_id,
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate requested shift exists and belongs to company
    shift_stmt = select(Shift).where(
        Shift.id == payload.requested_shift_id,
        Shift.company_id == company_id,
        Shift.deleted_at.is_(None),
    )
    shift_res = await db.execute(shift_stmt)
    requested_shift = shift_res.scalar_one_or_none()
    if not requested_shift:
        raise HTTPException(status_code=404, detail="Requested shift not found")

    # Check for existing pending request for same period
    # Note: In production, this would use a dedicated ShiftChangeRequest model
    # For now, we'll store in shift_plan_entries with a special status

    # Create a shift plan entry for the change request period
    end_date = payload.end_date or payload.start_date
    if end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date must be after or equal to start date")

    # Get or create manual plan for the period
    from app.attendance.routers.rosters import _get_or_create_manual_plan
    from app.models.shift_plan import ShiftPlanEntry, ShiftType

    current_date = payload.start_date
    created_entries = []

    while current_date <= end_date:
        plan = await _get_or_create_manual_plan(db, company_id, current_date)

        # Check for existing entry
        existing_stmt = select(ShiftPlanEntry).where(
            ShiftPlanEntry.plan_id == plan.id,
            ShiftPlanEntry.employee_id == employee.id,
            ShiftPlanEntry.shift_date == current_date,
        )
        existing_res = await db.execute(existing_stmt)
        existing = existing_res.scalar_one_or_none()

        if existing:
            # Update existing as change request
            existing.shift_type = ShiftType.DAY  # Will be overridden by shift_id
            existing.shift_id = requested_shift.id
            existing.start_time = requested_shift.start_time
            existing.end_time = requested_shift.end_time
            existing.notes = f"SHIFT_CHANGE_REQUEST: {payload.reason}"
            existing.approval_status = EntryApprovalStatus.PENDING
        else:
            entry = ShiftPlanEntry(
                plan_id=plan.id,
                company_id=company_id,
                employee_id=employee.id,
                shift_date=current_date,
                shift_type=ShiftType.DAY,
                shift_id=requested_shift.id,
                start_time=requested_shift.start_time,
                end_time=requested_shift.end_time,
                approval_status=EntryApprovalStatus.PENDING,
                notes=f"SHIFT_CHANGE_REQUEST: {payload.reason}",
            )
            db.add(entry)

        created_entries.append(current_date)
        current_date += timedelta(days=1)

    await db.commit()

    return {
        "success": True,
        "message": f"Shift change request submitted for {len(created_entries)} day(s).",
        "data": {
            "employee_id": str(employee.id),
            "employee_name": f"{employee.first_name} {employee.last_name}".strip(),
            "current_shift": employee.shift,
            "requested_shift_id": str(requested_shift.id),
            "requested_shift_name": requested_shift.name,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat() if payload.end_date else None,
            "reason": payload.reason,
            "status": "pending",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "dates_requested": [d.isoformat() for d in created_entries],
        },
        "error": None,
    }


# ── Existing Endpoint ────────────────────────────────────────────────────────

@router.get(
    "/face/me",
    status_code=status.HTTP_200_OK,
    summary="Get today's real attendance, shift, break, and biometric status for current employee",
)
async def get_today_punch_state(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Retrieve verified attendance, shift timings, break sessions, and face enrollment state."""
    user_id = _get_user_id(claims)
    service = AttendanceHistoryService(db)
    result = await service.get_today_attendance(user_id)

    # Validate against response schema
    validated = AttendanceTodayResponse(**result)

    return {
        "success": True,
        "message": result.get("message", "Today's punch status retrieved."),
        "data": validated.model_dump(mode="json"),
        "error": None,
    }
