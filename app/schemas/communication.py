"""Pydantic v2 schemas for the Internal Communication module."""

from __future__ import annotations

from datetime import date, datetime, time
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANNOUNCEMENT_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}
ANNOUNCEMENT_STATUSES = {"DRAFT", "PUBLISHED", "ARCHIVED"}
EVENT_TYPES = {
    "Town Hall", "Festival", "Training", "Workshop", "Sports", "CSR",
    "Celebration", "Meeting", "Other",
}
EVENT_STATUSES = {"SCHEDULED", "COMPLETED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Announcements Schemas
# ---------------------------------------------------------------------------

class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    description: str = Field(..., min_length=1)
    category: str = Field("General", max_length=50)
    priority: str = "MEDIUM"
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    visibility: str = "ALL_EMPLOYEES"
    publish_date: date = Field(default_factory=date.today)
    expiry_date: date | None = None
    is_pinned: bool = False
    status: str = "DRAFT"

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        v = v.upper()
        if v not in ANNOUNCEMENT_PRIORITIES:
            raise ValueError("priority must be LOW, MEDIUM, HIGH, or URGENT")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in ANNOUNCEMENT_STATUSES:
            raise ValueError("status must be DRAFT, PUBLISHED, or ARCHIVED")
        return v


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    category: str
    priority: str
    department: str | None
    branch: str | None
    visibility: str
    publish_date: date
    expiry_date: date | None
    is_pinned: bool
    status: str
    created_by: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Company News Schemas
# ---------------------------------------------------------------------------

class CompanyNewsCreate(BaseModel):
    headline: str = Field(..., min_length=1, max_length=150)
    summary: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    cover_image: str | None = Field(None, max_length=500)
    category: str = Field(..., min_length=1, max_length=50)
    department: str | None = Field(None, max_length=100)
    publish_date: date = Field(default_factory=date.today)
    expiry_date: date | None = None
    status: str = "DRAFT"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in ANNOUNCEMENT_STATUSES:
            raise ValueError("status must be DRAFT, PUBLISHED, or ARCHIVED")
        return v


class CompanyNewsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    headline: str
    summary: str
    content: str
    cover_image: str | None
    category: str
    author_id: uuid.UUID
    department: str | None
    publish_date: date
    expiry_date: date | None
    status: str
    views_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Company Event Schemas
# ---------------------------------------------------------------------------

class CompanyEventCreate(BaseModel):
    event_title: str = Field(..., min_length=1, max_length=150)
    description: str = Field(..., min_length=1)
    event_type: str = Field(..., description="Event Type")
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    location: str | None = Field(None, max_length=255)
    meeting_link: str | None = Field(None, max_length=500)
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    max_participants: int | None = Field(None, ge=1)
    registration_required: bool = False
    status: str = "SCHEDULED"

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of: {', '.join(EVENT_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in EVENT_STATUSES:
            raise ValueError("status must be SCHEDULED, COMPLETED, or CANCELLED")
        return v

    @model_validator(mode="after")
    def validate_event_times(self) -> CompanyEventCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")
        if self.end_date == self.start_date and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time on the same day.")
        return self


class CompanyEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_title: str
    description: str
    event_type: str
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    location: str | None
    meeting_link: str | None
    organizer_id: uuid.UUID
    department: str | None
    branch: str | None
    max_participants: int | None
    registration_required: bool
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Polls Schemas
# ---------------------------------------------------------------------------

class OptionCreate(BaseModel):
    option_text: str = Field(..., min_length=1, max_length=150)


class OptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    poll_id: uuid.UUID
    option_text: str


class PollCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    start_date: date
    end_date: date
    allow_multiple_selection: bool = False
    anonymous_voting: bool = False
    target_audience: str | None = Field(None, max_length=100)
    options: list[OptionCreate] = Field(..., min_items=2, description="At least two choices required")

    @model_validator(mode="after")
    def validate_poll_dates(self) -> PollCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")
        return self


class PollResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    description: str | None
    start_date: date
    end_date: date
    allow_multiple_selection: bool
    anonymous_voting: bool
    target_audience: str | None
    status: str
    created_by: uuid.UUID
    created_at: datetime
    options: list[OptionResponse] = []


# ---------------------------------------------------------------------------
# Analytics & View Responses
# ---------------------------------------------------------------------------

class AnnouncementAnalytics(BaseModel):
    views_count: int
    read_percentage: float
    unread_employees_count: int


class PollAnalytics(BaseModel):
    total_votes: int
    participation_rate: float
    option_counts: dict[str, int]


class EventAnalytics(BaseModel):
    registrations_count: int
    max_limit: int | None
    attendance_rate: float


# ---------------------------------------------------------------------------
# Dashboard Schema
# ---------------------------------------------------------------------------

class CommunicationDashboardView(BaseModel):
    pinned_announcements: list[AnnouncementResponse]
    recent_announcements: list[AnnouncementResponse]
    company_news: list[CompanyNewsResponse]
    upcoming_events: list[CompanyEventResponse]
    active_polls: list[PollResponse]
