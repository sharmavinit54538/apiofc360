"""Pydantic schemas for AI Employee Health module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EmployeeHealthDashboardResponse(BaseModel):
    """Employee Health Dashboard KPIs supporting dual camelCase and snake_case for frontend thunk fetchEmployeeHealthSentiment."""

    # camelCase properties for frontend thunk compatibility
    wellbeingScore: float = Field(84.5, description="Organization Wellbeing Score (0-100)")
    burnoutRisk: float = Field(14.2, description="Burnout Risk Index (0-100)")
    avgWorkload: str = Field("41.5 hrs/week", description="Average Weekly Workload")
    otHours: float = Field(18.5, description="Total Overtime Hours")
    burnoutTrend: list[dict[str, Any]] = Field(default_factory=list)
    teamOvertime: list[dict[str, Any]] = Field(default_factory=list)
    stressIndicators: list[dict[str, Any]] = Field(default_factory=list)
    wellbeingBreakdown: dict[str, float] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)

    # Standard snake_case properties
    wellbeing_score: float = Field(84.5, description="Organization Wellbeing Score")
    burnout_risk: float = Field(14.2, description="Burnout Risk Index")
    avg_workload: str = Field("41.5 hrs/week", description="Average Weekly Workload")
    ot_hours: float = Field(18.5, description="Total Overtime Hours")

    # Additional KPIs
    high_risk_employees: int = Field(2, description="Count of employees with high burnout risk")
    employees_under_monitoring: int = Field(5, description="Count of employees under active wellness monitoring")
    healthy_employee_pct: float = Field(85.8, description="Percentage of healthy workforce")
    wellness_trend: str = Field("STABLE", description="IMPROVING | STABLE | DECLINING")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WellbeingScoreResponse(BaseModel):
    """Wellbeing Score calculation breakdown."""

    score: float = Field(84.5, ge=0.0, le=100.0)
    attendance_factor: float = 92.0
    leave_usage_factor: float = 88.0
    workload_factor: float = 82.5
    overtime_factor: float = 79.0
    stress_signals_factor: float = 85.0
    insights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BurnoutItem(BaseModel):
    """Burnout risk record for an employee."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    burnout_risk: float = Field(..., ge=0.0, le=100.0)
    risk_level: str = Field("LOW", description="HIGH | MEDIUM | LOW")
    confidence_score: float = 92.0
    consecutive_working_days: int = 5
    weekly_ot_hours: float = 4.0
    recommendation: str

    model_config = ConfigDict(from_attributes=True)


class BurnoutRiskResponse(BaseModel):
    """Burnout Risk analysis."""

    overall_burnout_index: float = 14.2
    risk_level: str = "LOW"
    confidence_score: float = 92.5
    high_risk_count: int = 2
    items: list[BurnoutItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WorkloadAnalysisResponse(BaseModel):
    """Workload Analysis summary."""

    avg_weekly_hours: float = 41.5
    capacity_utilization_pct: float = 88.5
    overloaded_count: int = 3
    underutilized_count: int = 2
    department_workload: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OvertimeResponse(BaseModel):
    """Overtime Monitoring summary."""

    total_ot_hours: float = 18.5
    daily_ot_avg: float = 0.8
    weekly_ot_avg: float = 4.2
    monthly_ot_total: float = 18.5
    team_overtime: list[dict[str, Any]] = Field(default_factory=list)
    top_ot_employees: list[dict[str, Any]] = Field(default_factory=list)
    budget_impact: float = 14800.0

    model_config = ConfigDict(from_attributes=True)


class StressIndicatorsResponse(BaseModel):
    """Stress Indicators analysis."""

    stress_index: float = 22.5
    risk_category: str = "NORMAL"
    stress_indicators: list[dict[str, Any]] = Field(default_factory=list)
    ai_insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BurnoutTrendResponse(BaseModel):
    """Burnout Trend data."""

    period: str = "Monthly"
    burnout_trend: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TeamOvertimeResponse(BaseModel):
    """Team Overtime breakdown."""

    team_overtime: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeeHealthAnalyticsResponse(BaseModel):
    """Overall Employee Health Analytics."""

    wellness_trend: list[dict[str, Any]] = Field(default_factory=list)
    burnout_distribution: list[dict[str, Any]] = Field(default_factory=list)
    overtime_distribution: list[dict[str, Any]] = Field(default_factory=list)
    workload_distribution: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeeHealthDetailResponse(BaseModel):
    """Employee health detail."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    wellbeing_score: float = 85.0
    burnout_risk_level: str = "LOW"
    weekly_workload_hours: float = 40.0
    monthly_ot_hours: float = 2.5
    stress_level: str = "LOW"
    recommendation: str = "Workload is well-balanced."

    model_config = ConfigDict(from_attributes=True)


# Request Models
class AnalyzeHealthPayload(BaseModel):
    """Payload to analyze employee health."""

    department_id: Optional[uuid.UUID] = None


class BurnoutAnalysisPayload(BaseModel):
    """Payload to run burnout analysis."""

    department_id: Optional[uuid.UUID] = None


class WorkloadAnalysisPayload(BaseModel):
    """Payload to analyze workload."""

    department_id: Optional[uuid.UUID] = None


class GenerateInsightsPayload(BaseModel):
    """Payload to generate AI health insights."""

    department_id: Optional[uuid.UUID] = None
