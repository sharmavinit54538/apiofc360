"""Pydantic schemas for AI Workforce Planning module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class WorkforceDashboardResponse(BaseModel):
    """Workforce Planning Dashboard KPIs."""

    planned_hires: int = Field(..., description="Count of planned hiring requisitions")
    open_positions: int = Field(..., description="Currently active open job requisitions")
    capacity_utilization_pct: float = Field(..., description="Current workforce capacity utilization percentage")
    workforce_size: int = Field(..., description="Total headcount size")
    active_employees: int = Field(..., description="Active employees headcount")
    total_departments: int = Field(..., description="Total active departments count")
    forecast_horizon: str = Field("Q3 2026 - Q2 2027", description="Planning forecast window")
    hiring_budget: float = Field(..., description="Allocated annual hiring budget")
    vacancy_rate: float = Field(..., description="Open vacancy rate percentage")

    model_config = ConfigDict(from_attributes=True)


class ForecastItem(BaseModel):
    """Hiring forecast item."""

    period_label: str
    planned_hiring: int = 0
    required_hiring: int = 0
    predicted_hiring: int = 0
    hiring_cost: float = 0.0
    confidence_score: float = 90.0

    model_config = ConfigDict(from_attributes=True)


class HiringForecastResponse(BaseModel):
    """Hiring Forecast across periods."""

    period: str = "Quarterly"
    planned_hiring: int = 0
    required_hiring: int = 0
    predicted_hiring: int = 0
    hiring_cost: float = 0.0
    confidence_score: float = 91.5
    forecast_data: list[ForecastItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DepartmentCapacityItem(BaseModel):
    """Department Capacity vs Demand item."""

    department: str
    current_capacity: int
    projected_demand: int
    available_employees: int
    required_employees: int
    gap_analysis: int
    capacity_pct: float
    utilization_pct: float

    model_config = ConfigDict(from_attributes=True)


class CapacityDemandResponse(BaseModel):
    """Capacity vs Demand analysis matrix."""

    total_capacity: int
    total_demand: int
    department_capacity: list[DepartmentCapacityItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DepartmentCapacityPlanItem(BaseModel):
    """Department Capacity Planning details."""

    department: str
    current_headcount: int
    required_headcount: int
    vacant_positions: int
    critical_roles: list[str] = Field(default_factory=list)
    bench_strength: int = 0
    future_hiring_needs: int = 0

    model_config = ConfigDict(from_attributes=True)


class CapacityPlanningResponse(BaseModel):
    """Department Capacity Planning list."""

    total_required_headcount: int
    departments: list[DepartmentCapacityPlanItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ResourceUtilizationResponse(BaseModel):
    """Resource Utilization analysis."""

    overall_utilization_pct: float = 88.5
    billable_utilization_pct: float = 82.0
    idle_capacity_pct: float = 11.5
    overloaded_teams_count: int = 2
    department_utilization: list[dict[str, Any]] = Field(default_factory=list)
    ai_insights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class FutureWorkforceNeedsResponse(BaseModel):
    """Future Workforce Needs predictions."""

    future_skills_required: list[str] = Field(default_factory=list)
    roles_in_demand: list[str] = Field(default_factory=list)
    retirement_impact_count: int = 2
    predicted_attrition_count: int = 5
    internal_mobility_opportunities: int = 12
    expansion_roles: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OptimizationItem(BaseModel):
    """Workforce optimization recommendation."""

    category: str = Field(..., description="RESOURCE_REALLOCATION | HIRING_OPTIMIZATION | COST_SAVINGS | INTERNAL_PROMOTION")
    title: str
    description: str
    impact_level: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    estimated_cost_savings: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class WorkforceOptimizationResponse(BaseModel):
    """Workforce Optimization recommendations list."""

    total_recommendations: int
    recommendations: list[OptimizationItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DepartmentBudgetItem(BaseModel):
    """Department hiring budget item."""

    department: str
    planned_budget: float
    actual_budget: float
    variance: float

    model_config = ConfigDict(from_attributes=True)


class HiringBudgetResponse(BaseModel):
    """Hiring Budget Analysis."""

    planned_budget: float
    actual_budget: float
    budget_variance: float
    cost_per_hire: float = 45000.0
    department_budgets: list[DepartmentBudgetItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WorkforceAnalyticsResponse(BaseModel):
    """Workforce Analytics summary."""

    headcount_trend: list[dict[str, Any]] = Field(default_factory=list)
    hiring_trend: list[dict[str, Any]] = Field(default_factory=list)
    attrition_trend: list[dict[str, Any]] = Field(default_factory=list)
    productivity_trend: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DepartmentWorkforceDetailResponse(BaseModel):
    """Department workforce detail."""

    department_id: uuid.UUID
    department_name: str
    headcount: int
    utilization_pct: float
    open_positions: int
    skills_gap: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeeWorkforceDetailResponse(BaseModel):
    """Employee workforce detail."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    role: str
    utilization_pct: float = 90.0
    flight_risk_level: str = Field("LOW", description="HIGH | MEDIUM | LOW")

    model_config = ConfigDict(from_attributes=True)


# Request Models
class AnalyzeWorkforcePayload(BaseModel):
    """Payload to analyze workforce."""

    department_id: Optional[uuid.UUID] = None


class ForecastWorkforcePayload(BaseModel):
    """Payload to forecast workforce demand."""

    horizon_quarters: int = 4
    department_id: Optional[uuid.UUID] = None


class OptimizeWorkforcePayload(BaseModel):
    """Payload to generate workforce optimization plan."""

    target_savings_pct: float = 10.0


class CapacityAnalysisPayload(BaseModel):
    """Payload to run capacity analysis."""

    department_id: Optional[uuid.UUID] = None
