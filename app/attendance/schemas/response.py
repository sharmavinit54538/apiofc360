"""Daily Face Attendance response serialization schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AttendanceResponse(BaseModel):
    """Daily Face Attendance response serialization schema."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: Optional[str] = None
    company_id: Optional[uuid.UUID] = None
    date: date
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    face_image_url: Optional[str] = None
    checkout_image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    working_hours: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class AttendanceTodayResponse(BaseModel):
    """Response representing today's attendance state for current employee."""
    checked_in: bool
    checked_out: bool
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    working_hours: Optional[float] = None
    message: str
