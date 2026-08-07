"""Pydantic schemas for AI Leave Assistant module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class LeaveDashboardResponse(BaseModel):
    """Leave Dashboard KPIs."""

    pending_leave_requests: int = Field(..., description="Count of pending leave applications")
    approved_requests: int = Field(..., description="Count of approved leave applications")
    rejected_requests: int = Field(..., description="Count of rejected leave applications")
    approval_suggestions_count: int = Field(..., description="Count of ready AI approval recommendations")
    leave_conflicts_count: int = Field(..., description="Count of detected leave conflicts")
    team_availability_percentage: float = Field(..., description="Current team availability percentage rate")
    average_approval_time_hours: float = Field(..., description="Average leave approval response time in hours")
    employees_on_leave_today: int = Field(..., description="Count of employees currently on active leave today")

    model_config = ConfigDict(from_attributes=True)


class ForecastItem(BaseModel):
    """Leave forecast data point."""

    period_label: str
    expected_leave_days: float = 0.0
    peak_risk_level: str = Field("LOW", description="HIGH | MEDIUM | LOW")
    affected_department: str = "General"

    model_config = ConfigDict(from_attributes=True)


class LeaveForecastResponse(BaseModel):
    """Leave Forecast series across upcoming weeks or months."""

    period: str = "Next 12 Weeks"
    group_by: str = "weekly"
    data: list[ForecastItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LeaveTypeDistributionItem(BaseModel):
    """Single leave type count & percentage."""

    leave_type: str
    count: int = 0
    percentage: float = 0.0
    days_taken: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class LeaveDistributionResponse(BaseModel):
    """Leave Type Distribution breakdown."""

    total_leaves: int
    distribution: list[LeaveTypeDistributionItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ApprovalSuggestionItem(BaseModel):
    """AI Leave Approval suggestion record."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    department: str
    leave_type: str
    start_date: str
    end_date: str
    total_days: float
    recommendation: str = Field(..., description="APPROVE | REJECT | DISCUSS | MANUAL_REVIEW")
    confidence_score: float = Field(..., ge=0.0, le=100.0)
    reason: str
    leave_balance_remaining: float = 10.0
    team_availability_pct: float = 85.0

    model_config = ConfigDict(from_attributes=True)


class LeaveApprovalSuggestionsResponse(BaseModel):
    """AI Leave Approval Suggestions list."""

    total_pending: int
    items: list[ApprovalSuggestionItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ConflictItem(BaseModel):
    """Leave conflict entry."""

    id: uuid.UUID
    conflict_type: str = Field(..., description="SAME_TEAM_OVERLAP | CRITICAL_RESOURCE_UNAVAILABLE | MANAGER_UNAVAILABLE | HOLIDAY_OVERLAP | BLACKOUT_PERIOD")
    severity: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    affected_employees: list[str] = Field(default_factory=list)
    description: str
    suggested_resolution: str

    model_config = ConfigDict(from_attributes=True)


class LeaveConflictsResponse(BaseModel):
    """Leave conflicts detection list."""

    total_conflicts: int
    items: list[ConflictItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TeamAvailabilityResponse(BaseModel):
    """Team Availability Analysis metrics."""

    total_employees: int
    available_count: int
    on_leave_count: int
    availability_percentage: float
    department_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    shift_breakdown: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TrendItem(BaseModel):
    """Leave trend data point."""

    label: str
    leave_count: int = 0
    days_sum: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class LeaveTrendsResponse(BaseModel):
    """Leave Trends breakdown across time periods."""

    period: str = "Monthly"
    data: list[TrendItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LeaveAnalyticsResponse(BaseModel):
    """Leave Analytics Summary."""

    overall_availability_rate: float = 93.5
    peak_months: list[str] = Field(default_factory=list)
    avg_duration_days: float = 2.4
    type_distribution: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LeaveRequestDetailResponse(BaseModel):
    """Detailed Leave Request payload."""

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    department: str
    leave_type: str
    start_date: str
    end_date: str
    total_days: float
    reason: str
    status: str
    rejection_reason: Optional[str] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# Request Models
class AnalyzeLeaveRequestPayload(BaseModel):
    """Payload to analyze a leave request."""

    leave_request_id: uuid.UUID


class ForecastLeaveRequestPayload(BaseModel):
    """Payload to forecast leave demand."""

    department_id: Optional[uuid.UUID] = None
    weeks_ahead: int = 12


class GenerateSuggestionsPayload(BaseModel):
    """Payload to generate AI approval suggestions."""

    department_id: Optional[uuid.UUID] = None


class DetectConflictsPayload(BaseModel):
    """Payload to detect leave conflicts."""

    department_id: Optional[uuid.UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
