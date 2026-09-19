"""Daily Face Attendance response serialization schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

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
    captured_face_url: Optional[str] = None
    checkout_image_url: Optional[str] = None
    status: Optional[str] = "Present"
    punch_type: Optional[str] = "IN"
    verified: Optional[bool] = True
    punch_verified_by: Optional[str] = "FACE"
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy: Optional[float] = None
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    working_hours: Optional[float] = None
    break_duration: Optional[float] = 0.0
    liveness_score: Optional[float] = None
    face_distance: Optional[float] = None
    is_late: Optional[bool] = False
    late_minutes: Optional[int] = 0
    shift_id: Optional[uuid.UUID] = None
    shift_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EmployeeSummary(BaseModel):
    """Brief employee summary for attendance status."""
    id: uuid.UUID
    employee_id: str
    first_name: str
    last_name: str
    department: str
    designation: str
    branch: Optional[str] = None
    work_location: Optional[str] = None


class AttendanceTodayResponse(BaseModel):
    """Response representing today's attendance state for current employee."""
    checked_in: bool
    checked_out: bool
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    working_hours: Optional[float] = None
    break_duration_hours: Optional[float] = 0.0
    total_break_minutes: Optional[float] = 0.0
    is_on_break: Optional[bool] = False
    current_break: Optional[Dict[str, Any]] = None
    breaks: Optional[List[Dict[str, Any]]] = None
    is_late: Optional[bool] = False
    late_minutes: Optional[int] = 0
    shift: Optional[Dict[str, Any]] = None
    is_face_enrolled: Optional[bool] = False
    face_enrolled_at: Optional[str] = None
    verification_status: Optional[str] = None
    employee: Optional[EmployeeSummary] = None
    today_attendance: Optional[AttendanceResponse] = None
    message: str
