"""Daily Face Attendance paginated history response schema."""

from __future__ import annotations

from pydantic import BaseModel
from app.attendance.schemas.response import AttendanceResponse


class AttendanceHistoryResponse(BaseModel):
    """Paginated list of attendance history items."""
    page: int
    limit: int
    total: int
    items: list[AttendanceResponse]
