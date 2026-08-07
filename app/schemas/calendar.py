"""Pydantic v2 schemas for the Calendar Management module."""

from __future__ import annotations

from datetime import date, datetime, time
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_TYPE_VALUES = {
    "Holiday",
    "Meeting",
    "Birthday",
    "Work Anniversary",
    "Company Event",
    "Training",
    "Town Hall",
    "Payroll Day",
    "Leave Reminder",
    "Recruitment Event",
    "Other",
}

VISIBILITY_VALUES = {"PUBLIC", "DEPARTMENT_ONLY", "PRIVATE"}
STATUS_VALUES = {"DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"}
HOLIDAY_TYPE_VALUES = {"NATIONAL", "REGIONAL", "COMPANY_HOLIDAY"}
MEETING_MODE_VALUES = {"ONLINE", "OFFLINE", "HYBRID"}
MEETING_STATUS_VALUES = {"SCHEDULED", "COMPLETED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Calendar Event Schemas
# ---------------------------------------------------------------------------

class CalendarEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    description: str = Field(..., min_length=1)
    event_type: str = Field(..., description="Event Type")
    start_date: date
    end_date: date
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(None, max_length=255)
    meeting_link: str | None = Field(None, max_length=500)
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    visibility: str = "PUBLIC"
    status: str = "DRAFT"

    # Reminder configuration (minutes before event starts, e.g. [15, 60])
    reminder_minutes: list[int] = Field([], description="Minutes before event to trigger reminders")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in EVENT_TYPE_VALUES:
            raise ValueError(f"event_type must be one of: {', '.join(EVENT_TYPE_VALUES)}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError("visibility must be PUBLIC, DEPARTMENT_ONLY, or PRIVATE")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in STATUS_VALUES:
            raise ValueError("status must be DRAFT, PUBLISHED, CANCELLED, or COMPLETED")
        return v

    @model_validator(mode="after")
    def validate_dates(self) -> CalendarEventCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")
        return self


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    event_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(None, max_length=255)
    meeting_link: str | None = Field(None, max_length=500)
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    visibility: str | None = None
    status: str | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in EVENT_TYPE_VALUES:
            raise ValueError(f"event_type must be one of: {', '.join(EVENT_TYPE_VALUES)}")
        return v


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    event_type: str
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    location: str | None
    meeting_link: str | None
    department: str | None
    branch: str | None
    visibility: str
    status: str
    created_by: uuid.UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Holiday Schemas
# ---------------------------------------------------------------------------

class HolidayCreate(BaseModel):
    holiday_name: str = Field(..., min_length=1, max_length=150)
    holiday_date: date
    holiday_type: str = Field(..., description="NATIONAL / REGIONAL / COMPANY_HOLIDAY")
    branch: str | None = Field(None, max_length=100)
    description: str | None = None
    is_recurring: bool = False

    @field_validator("holiday_type")
    @classmethod
    def validate_holiday_type(cls, v: str) -> str:
        v = v.upper()
        if v not in HOLIDAY_TYPE_VALUES:
            raise ValueError("holiday_type must be NATIONAL, REGIONAL, or COMPANY_HOLIDAY")
        return v


class HolidayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    holiday_name: str
    holiday_date: date
    holiday_type: str
    branch: str | None
    description: str | None
    is_recurring: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Meeting Schemas
# ---------------------------------------------------------------------------

class MeetingParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str = Field(..., validation_alias="employee_name")


class MeetingCreate(BaseModel):
    meeting_title: str = Field(..., min_length=1, max_length=150)
    agenda: str | None = None
    meeting_mode: str = "ONLINE"
    meeting_link: str | None = Field(None, max_length=500)
    office_location: str | None = Field(None, max_length=255)
    meeting_date: date
    start_time: time
    end_time: time

    # List of Employee Profile UUIDs (not user IDs)
    participant_employee_ids: list[uuid.UUID] = Field([], description="Invite employee profile UUIDs")

    @field_validator("meeting_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.upper()
        if v not in MEETING_MODE_VALUES:
            raise ValueError("meeting_mode must be ONLINE, OFFLINE, or HYBRID")
        return v

    @model_validator(mode="after")
    def validate_times(self) -> MeetingCreate:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time.")
        return self


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meeting_title: str
    agenda: str | None
    organizer_id: uuid.UUID
    meeting_mode: str
    meeting_link: str | None
    office_location: str | None
    meeting_date: date
    start_time: time
    end_time: time
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Birthday & Anniversary Briefs
# ---------------------------------------------------------------------------

class BirthdayListItem(BaseModel):
    employee_name: str
    department: str
    designation: str
    age: int


class AnniversaryListItem(BaseModel):
    employee_name: str
    department: str
    years_completed: int


# ---------------------------------------------------------------------------
# Dashboard View
# ---------------------------------------------------------------------------

class CalendarDashboardView(BaseModel):
    today_events: list[CalendarEventResponse]
    upcoming_holidays: list[HolidayResponse]
    upcoming_birthdays: list[BirthdayListItem]
    upcoming_anniversaries: list[AnniversaryListItem]
    today_meetings: list[MeetingResponse]
    upcoming_company_events: list[CalendarEventResponse]
    department_events: list[CalendarEventResponse]
