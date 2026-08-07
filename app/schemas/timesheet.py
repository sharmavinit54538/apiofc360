"""Pydantic schemas for Timesheets and Timesheet Entries."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TimesheetEntryBase(BaseModel):
    project_id: str = Field(..., description="Project unique string identifier")
    monday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    tuesday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    wednesday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    thursday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    friday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    saturday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    sunday_hours: Decimal = Field(default=Decimal("0.00"), ge=0, le=24)
    description: Optional[str] = None


class TimesheetEntryCreate(TimesheetEntryBase):
    pass


class TimesheetEntryResponse(TimesheetEntryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    timesheet_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TimesheetBase(BaseModel):
    week_start_date: date = Field(..., description="Monday date of the target week")


class TimesheetCreate(TimesheetBase):
    entries: list[TimesheetEntryCreate] = Field(default_factory=list)


class TimesheetUpdate(BaseModel):
    status: Optional[str] = None  # DRAFT, PENDING, APPROVED, REJECTED
    entries: Optional[list[TimesheetEntryCreate]] = None


class TimesheetApprovalRequest(BaseModel):
    status: str = Field(..., pattern="^(APPROVED|REJECTED)$", description="Approved or rejected status")
    rejection_reason: Optional[str] = None


class TimesheetResponse(TimesheetBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    status: str
    submitted_at: Optional[datetime] = None
    approved_by_id: Optional[uuid.UUID] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    entries: list[TimesheetEntryResponse] = Field(default_factory=list)
