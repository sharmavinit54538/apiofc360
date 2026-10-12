"""Pydantic schemas for Shift Management APIs."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, Generic, List, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.attendance.utils.time_parse import InvalidTimeFormatError, parse_time_str
from app.schemas.common import APIResponse


# ─────────────────────────────────────────────────────────────────────────────
# Shift Schemas
# ─────────────────────────────────────────────────────────────────────────────

VALID_WORKING_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


class ShiftBase(BaseModel):
    """Base shift fields."""

    name: str = Field(..., min_length=2, max_length=100)
    code: str = Field(..., min_length=2, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    start_time: str = Field(..., description="Shift start time in HH:MM, H:MM, HH:MM AM/PM format")
    end_time: str = Field(..., description="Shift end time in HH:MM, H:MM, HH:MM AM/PM format")
    grace_period_minutes: int = Field(15, ge=0, le=120)
    break_duration_minutes: int = Field(60, ge=0, le=180)
    is_night_shift: bool = False
    night_premium_percent: float = Field(0.0, ge=0, le=100)
    working_days: List[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    is_active: bool = True
    is_default: bool = False
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
    description: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_and_normalize_time(cls, v: str) -> str:
        """Validate and normalize time to HH:MM format."""
        try:
            parsed = parse_time_str(v)
            return parsed.strftime("%H:%M")
        except InvalidTimeFormatError as exc:
            raise ValueError(str(exc))

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, v: List[str]) -> List[str]:
        if not v or len(v) == 0:
            raise ValueError("At least one working day must be selected.")
        normalized = []
        for d in v:
            clean = str(d).strip().capitalize()
            if clean not in VALID_WORKING_DAYS:
                raise ValueError(f"Invalid weekday: {d}. Must be one of {sorted(VALID_WORKING_DAYS)}.")
            normalized.append(clean)
        if len(normalized) != len(set(normalized)):
            raise ValueError("working_days cannot contain duplicates.")
        # Return in canonical order
        day_order = {d: i for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])}
        return sorted(normalized, key=lambda x: day_order[x])

    @field_validator("night_premium_percent")
    @classmethod
    def validate_night_premium(cls, v: float, info) -> float:
        if info.data.get("is_night_shift") is False and v > 0:
            return 0.0
        return v

    @model_validator(mode="after")
    def validate_shift_times(self) -> "ShiftBase":
        start = parse_time_str(self.start_time)
        end = parse_time_str(self.end_time)
        if start == end:
            raise ValueError("start_time must be different from end_time.")
        return self


class ShiftCreate(ShiftBase):
    """Schema for creating a new shift."""
    pass


class ShiftUpdate(BaseModel):
    """Schema for updating a shift (all fields optional)."""

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    code: Optional[str] = Field(None, min_length=2, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    grace_period_minutes: Optional[int] = Field(None, ge=0, le=120)
    break_duration_minutes: Optional[int] = Field(None, ge=0, le=180)
    is_night_shift: Optional[bool] = None
    night_premium_percent: Optional[float] = Field(None, ge=0, le=100)
    working_days: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
    description: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_and_normalize_time(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            parsed = parse_time_str(v)
            return parsed.strftime("%H:%M")
        except InvalidTimeFormatError as exc:
            raise ValueError(str(exc))

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        if len(v) == 0:
            raise ValueError("At least one working day must be selected.")
        normalized = []
        for d in v:
            clean = str(d).strip().capitalize()
            if clean not in VALID_WORKING_DAYS:
                raise ValueError(f"Invalid weekday: {d}. Must be one of {sorted(VALID_WORKING_DAYS)}.")
            normalized.append(clean)
        if len(normalized) != len(set(normalized)):
            raise ValueError("working_days cannot contain duplicates.")
        day_order = {d: i for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])}
        return sorted(normalized, key=lambda x: day_order[x])

    @field_validator("night_premium_percent")
    @classmethod
    def validate_night_premium(cls, v: Optional[float], info) -> Optional[float]:
        if v is not None and info.data.get("is_night_shift") is False and v > 0:
            return 0.0
        return v


class ShiftResponse(BaseModel):
    """Full shift response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    start_time: str  # HH:MM format
    end_time: str    # HH:MM format
    is_overnight: bool
    duration_minutes: int
    work_hours: float
    grace_period_minutes: int
    break_duration_minutes: int
    is_night_shift: bool
    night_premium_percent: float
    working_days: List[str]
    is_active: bool
    is_default: bool
    color: Optional[str]
    description: Optional[str]
    assigned_employees_count: int
    created_at: datetime
    updated_at: datetime


class ShiftMinimalResponse(BaseModel):
    """Minimal shift for /options endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    start_time: str
    end_time: str
    is_overnight: bool


class ShiftListResponse(BaseModel):
    """Paginated shift list response."""

    items: List[ShiftResponse]
    total: int
    page: int
    limit: int


# ─────────────────────────────────────────────────────────────────────────────
# Shift Assignment Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ShiftAssignRequest(BaseModel):
    """Request to assign shift to employees."""

    employee_ids: List[uuid.UUID] = Field(..., min_length=1, max_length=500)
    effective_date: date
    notes: Optional[str] = None


class ShiftAssignSkipped(BaseModel):
    employee_id: uuid.UUID
    reason: str


class ShiftAssignResponse(BaseModel):
    assigned_count: int
    skipped: List[ShiftAssignSkipped]
    effective_date: date


class AssignedEmployeeResponse(BaseModel):
    """Paginated assigned employees response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: str
    first_name: str
    last_name: str
    department: str
    designation: str
    branch: Optional[str]
    effective_from: date
    effective_to: Optional[date]


class AssignedEmployeesListResponse(BaseModel):
    items: List[AssignedEmployeeResponse]
    total: int
    page: int
    limit: int


# ─────────────────────────────────────────────────────────────────────────────
# Shift Change Request Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ShiftChangeRequestCreate(BaseModel):
    requested_shift_id: uuid.UUID
    effective_date: date
    reason: str = Field(..., min_length=10, max_length=500)

    @field_validator("effective_date")
    @classmethod
    def validate_effective_date(cls, v: date) -> date:
        # Must be tomorrow or later (checked in service with company tz)
        return v


class ShiftChangeRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: Optional[str] = None
    current_shift_id: Optional[uuid.UUID] = None
    current_shift_name: Optional[str] = None
    requested_shift_id: uuid.UUID
    requested_shift_name: Optional[str] = None
    effective_date: date
    reason: str
    status: str
    reviewed_by: Optional[uuid.UUID] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ShiftChangeRequestListResponse(BaseModel):
    items: List[ShiftChangeRequestResponse]
    total: int
    page: int
    limit: int


class ShiftChangeRequestAction(BaseModel):
    note: Optional[str] = None


class ShiftChangeRejectRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=500)


# ─────────────────────────────────────────────────────────────────────────────
# Roster Schemas
# ─────────────────────────────────────────────────────────────────────────────

class RosterEntryBase(BaseModel):
    employee_id: uuid.UUID
    date: date
    shift_id: Optional[uuid.UUID] = None
    shift_type: Optional[str] = Field(None, pattern=r"^(DAY|NIGHT|MORNING|EVENING|OVERTIME|ROTATION|HOLIDAY|OFF|WEEKLY_OFF|LEAVE|TRAINING|WFH)$")
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    working_hours: Optional[float] = None
    break_time: Optional[float] = None
    location: Optional[str] = None
    status: Literal["Approved", "Pending", "Rejected"] = "Approved"
    notes: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            parsed = parse_time_str(v)
            return parsed.strftime("%H:%M")
        except InvalidTimeFormatError as exc:
            raise ValueError(str(exc))


class RosterEntryCreate(RosterEntryBase):
    pass


class RosterEntryUpdate(BaseModel):
    shift_id: Optional[uuid.UUID] = None
    shift_type: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    working_hours: Optional[float] = None
    break_time: Optional[float] = None
    location: Optional[str] = None
    status: Optional[Literal["Approved", "Pending", "Rejected"]] = None
    notes: Optional[str] = None


class RosterEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    department: str
    designation: str
    date: date
    shift: str
    shift_id: Optional[uuid.UUID] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    working_hours: Optional[float] = None
    break_time: Optional[float] = None
    location: Optional[str] = None
    manager: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime


class RosterListResponse(BaseModel):
    items: List[RosterEntryResponse]
    total: int
    page: int
    limit: int


# ─────────────────────────────────────────────────────────────────────────────
# Self Schedule Schema
# ─────────────────────────────────────────────────────────────────────────────

class ScheduleShiftInfo(BaseModel):
    id: Optional[uuid.UUID] = None
    name: str
    code: Optional[str] = None
    start_time: str
    end_time: str
    is_overnight: bool
    source: Literal["roster", "assignment", "company_default", "fallback"]


class ScheduleToday(BaseModel):
    date: date
    day: str
    shift_name: str
    start_time: str
    end_time: str
    is_overnight: bool
    is_off: bool
    is_holiday: bool
    holiday_name: Optional[str] = None
    source: Literal["roster", "assignment", "company_default", "fallback"]
    checked_in: bool
    checked_out: bool
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    working_hours: Optional[float] = None
    is_late: bool
    late_minutes: int


class ScheduleUpcoming(BaseModel):
    date: date
    day: str
    shift_name: str
    start_time: str
    end_time: str
    is_overnight: bool
    is_off: bool
    is_holiday: bool
    holiday_name: Optional[str] = None
    source: Literal["roster", "assignment", "company_default", "fallback"]
    working_hours: float


class ScheduleHistory(BaseModel):
    attendance_id: Optional[uuid.UUID] = None
    date: date
    day: str
    shift_name: str
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    working_hours: Optional[float] = None
    overtime_hours: float = 0.0
    status: Literal["Present", "Late", "Half Day", "Absent", "On Leave", "Off", "Holiday", "Auto Closed"]
    is_late: bool
    late_minutes: int
    is_early_checkout: bool
    early_minutes: int
    auto_closed: bool


class SelfScheduleResponse(BaseModel):
    has_assigned_shift: bool
    timezone: str
    employee: Dict[str, Any]
    current_shift: Optional[ScheduleShiftInfo] = None
    today: Optional[ScheduleToday] = None
    upcoming: List[ScheduleUpcoming] = []
    history: List[ScheduleHistory] = []