"""Pydantic schemas for AI Attendance Monitor module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class AttendanceDashboardResponse(BaseModel):
    """Attendance Dashboard KPIs."""

    attendance_health_score: float = Field(..., description="Overall attendance health score (0-100)")
    total_attendance_percentage: float = Field(..., description="Present employee percentage rate")
    total_anomalies: int = Field(..., description="Total detected attendance anomalies")
    late_arrivals: int = Field(..., description="Count of late arrivals today")
    overtime_hours: float = Field(..., description="Total overtime hours logged")
    today_present_employees: int = Field(..., description="Count of employees present today")
    today_absent_employees: int = Field(..., description="Count of employees absent today")

    model_config = ConfigDict(from_attributes=True)


class TrendItem(BaseModel):
    """Single trend data point."""

    label: str
    present_count: int = 0
    total_count: int = 0
    attendance_percentage: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class AttendanceTrendResponse(BaseModel):
    """Attendance Trend grouped data."""

    period: str
    group_by: str
    data: list[TrendItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LateArrivalItem(BaseModel):
    """Late arrival entry per employee."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    shift_name: str = "General Shift"
    expected_time: str = "09:00 AM"
    actual_time: str
    delay_minutes: int
    frequency: int = 1

    model_config = ConfigDict(from_attributes=True)


class LateArrivalsResponse(BaseModel):
    """Late arrivals chart and list breakdown."""

    period: str
    total_late: int
    data: list[LateArrivalItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AnomalyItem(BaseModel):
    """Attendance anomaly detail record."""

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    department: str
    anomaly_type: str = Field(..., description="MISSING_CHECKOUT | DUPLICATE_PUNCH | GEOFENCE_VIOLATION | SHIFT_TIMING_BREACH | NIGHT_SHIFT_VIOLATION")
    description: str
    date: str
    severity: str = Field("HIGH", description="HIGH | MEDIUM | LOW")

    model_config = ConfigDict(from_attributes=True)


class AnomaliesResponse(BaseModel):
    """Attendance anomalies detection list."""

    total_anomalies: int
    items: list[AnomalyItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AbsencePatternItem(BaseModel):
    """AI Absence pattern detection insight."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    pattern_type: str = Field(..., description="FRIDAY_ABSENCE | MONDAY_ABSENCE | LONG_WEEKEND | REPEATED_LEAVE | SICK_LEAVE_SPIKE | UNAUTHORIZED")
    details: str
    risk_level: str = Field("HIGH", description="HIGH | MEDIUM | LOW")

    model_config = ConfigDict(from_attributes=True)


class AbsencePatternResponse(BaseModel):
    """Absence pattern analysis results."""

    patterns_detected: int
    items: list[AbsencePatternItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OvertimeResponse(BaseModel):
    """Overtime tracking metrics."""

    daily_ot_hours: float = 0.0
    weekly_ot_hours: float = 0.0
    monthly_ot_hours: float = 0.0
    budget_impact_amount: float = 0.0
    department_wise_ot: list[dict[str, Any]] = Field(default_factory=list)
    employee_wise_ot: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ShiftViolationItem(BaseModel):
    """Shift breach or violation entry."""

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    shift_name: str
    violation_type: str = Field(..., description="MISSED_SHIFT | EARLY_LOGOUT | LATE_LOGIN | NO_PUNCH | MULTIPLE_PUNCH")
    date: str
    details: str

    model_config = ConfigDict(from_attributes=True)


class ShiftViolationsResponse(BaseModel):
    """Shift violations list."""

    total_violations: int
    items: list[ShiftViolationItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AttendanceHealthScoreResponse(BaseModel):
    """Comprehensive composite attendance health score."""

    overall_score: float = Field(..., ge=0.0, le=100.0)
    attendance_rate: float = 0.0
    late_rate: float = 0.0
    leave_rate: float = 0.0
    ot_rate: float = 0.0
    shift_compliance_rate: float = 0.0
    policy_violations_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class WatchlistItem(BaseModel):
    """Employee at risk of chronic absenteeism."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    absent_days: int
    late_count: int
    attendance_percentage: float
    risk_level: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    recommendation: str

    model_config = ConfigDict(from_attributes=True)


class WatchlistResponse(BaseModel):
    """Absentee Watchlist breakdown."""

    total_at_risk: int
    items: list[WatchlistItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
