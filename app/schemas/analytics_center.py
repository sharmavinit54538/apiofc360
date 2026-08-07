"""Pydantic schemas for AI Analytics Center module APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AnalyticsKPIItem(BaseModel):
    """Specific KPI metric item."""

    key: str = Field("workforce_health", description="Metric key")
    label: str = Field("Workforce Health Score", description="Metric display name")
    value: Any = Field(92.4, description="Current value")
    change: str = Field("+2.4%", description="Trend change indicator")
    trend: str = Field("UP", description="UP | DOWN | STABLE")
    category: str = Field("Workforce", description="Category grouping")

    model_config = ConfigDict(from_attributes=True)


class HeadcountForecastItem(BaseModel):
    """Headcount forecast monthly point."""

    period: str = Field("Aug 2026", description="Month or Quarter")
    actual_headcount: Optional[int] = Field(48, description="Actual headcount")
    forecast_headcount: int = Field(52, description="AI predicted headcount")
    hiring_impact: int = Field(5, description="Expected hires")
    attrition_impact: int = Field(1, description="Expected departures")

    model_config = ConfigDict(from_attributes=True)


class HiringDemandItem(BaseModel):
    """Department hiring demand item."""

    department: str = Field("Engineering", description="Department name")
    open_positions: int = Field(8, description="Current vacancies")
    demand_level: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    hiring_velocity: str = Field("18 days", description="Avg days to hire")
    estimated_cost: str = Field("$24,000", description="Cost estimate")

    model_config = ConfigDict(from_attributes=True)


class PayrollTrendItem(BaseModel):
    """Monthly payroll trend item."""

    month: str = Field("Jul 2026", description="Month")
    payroll_cost: float = Field(240000.0, description="Base payroll cost")
    overtime_cost: float = Field(18500.0, description="Overtime cost")
    forecast_cost: float = Field(255000.0, description="AI predicted total")

    model_config = ConfigDict(from_attributes=True)


class SkillGapItem(BaseModel):
    """Skill gap analysis item."""

    skill_name: str = Field("Cloud Architecture (AWS)", description="Skill title")
    department: str = Field("Engineering", description="Department")
    current_level: float = Field(3.2, description="Current level 1-5")
    required_level: float = Field(4.5, description="Required level 1-5")
    gap_index: float = Field(1.3, description="Gap index")
    training_recommendation: str = Field("AWS Solutions Architect Professional Certification Course", description="Course recommendation")

    model_config = ConfigDict(from_attributes=True)


class AttritionRiskItem(BaseModel):
    """High flight risk employee item."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    flight_risk_score: float = Field(84.5, description="Risk score 0-100")
    risk_factors: list[str] = Field(default_factory=list, description="Key risk drivers")
    recommendation: str = Field("Schedule 1-on-1 retention review and evaluate market pay adjustments.")

    model_config = ConfigDict(from_attributes=True)


class ExecutiveSummaryData(BaseModel):
    """Executive summary payload for AI Analytics Center."""

    totalInsights: int = Field(28, description="Total AI insights generated")
    total_insights: int = Field(28, description="Total AI insights generated")
    executiveSummary: str = Field("Workforce health remains strong at 92.4% with optimal hiring velocity across Core Engineering and Sales.", description="Executive summary markdown")
    executive_summary: str = Field("Workforce health remains strong at 92.4% with optimal hiring velocity across Core Engineering and Sales.", description="Executive summary markdown")
    recommendations: list[str] = Field(default_factory=list, description="Top actionable recommendations")
    keyInsights: list[str] = Field(default_factory=list, description="Key insights list")
    risks: list[str] = Field(default_factory=list, description="Critical risks list")
    opportunities: list[str] = Field(default_factory=list, description="Growth opportunities")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AnalyticsDashboardData(BaseModel):
    """Data payload structure for fetchAIInsightsDashboard thunk."""

    kpis: list[dict[str, Any]] = Field(default_factory=list)
    summary: ExecutiveSummaryData = Field(default_factory=ExecutiveSummaryData)
    headcountForecast: list[HeadcountForecastItem] = Field(default_factory=list)
    headcount_forecast: list[HeadcountForecastItem] = Field(default_factory=list)
    hiringDemand: list[HiringDemandItem] = Field(default_factory=list)
    hiring_demand: list[HiringDemandItem] = Field(default_factory=list)
    payrollTrend: list[PayrollTrendItem] = Field(default_factory=list)
    payroll_trend: list[PayrollTrendItem] = Field(default_factory=list)
    skillGap: list[SkillGapItem] = Field(default_factory=list)
    skill_gap: list[SkillGapItem] = Field(default_factory=list)
    recruitment: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    employeeHealth: dict[str, Any] = Field(default_factory=dict)
    employee_health: dict[str, Any] = Field(default_factory=dict)
    compliance: dict[str, Any] = Field(default_factory=dict)
    attrition: dict[str, Any] = Field(default_factory=dict)
    charts: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AnalyticsKPIsResponse(BaseModel):
    """KPI metrics summary."""

    total_ai_insights: int = 28
    predictive_models_count: int = 12
    workforce_health_score: float = 92.4
    attrition_risk_pct: float = 3.8
    hiring_efficiency_pct: float = 88.5
    employee_satisfaction_score: float = 4.2
    payroll_health_pct: float = 96.0
    compliance_score: float = 92.5
    productivity_index: float = 94.0
    organization_efficiency: float = 91.2
    open_positions: int = 12
    active_employees: int = 48
    kpis: list[AnalyticsKPIItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HeadcountForecastResponse(BaseModel):
    """Headcount forecast response."""

    current_headcount: int = 48
    ai_forecast_headcount: int = 56
    growth_pct: float = 16.6
    hiring_impact: int = 10
    attrition_impact: int = 2
    forecast: list[HeadcountForecastItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HiringDemandResponse(BaseModel):
    """Hiring demand response."""

    open_positions: int = 12
    hiring_velocity: str = "18 days"
    hiring_cost: str = "$42,000"
    time_to_fill: str = "21 days"
    demand: list[HiringDemandItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PayrollTrendResponse(BaseModel):
    """Payroll trend response."""

    monthly_payroll_cost: float = 240000.0
    forecast_payroll_cost: float = 255000.0
    overtime_cost: float = 18500.0
    cost_savings: float = 14200.0
    budget_variance: float = 2.1
    trend: list[PayrollTrendItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SkillGapResponse(BaseModel):
    """Skill gap analysis response."""

    total_skills_analyzed: int = 24
    critical_gaps_count: int = 4
    items: list[SkillGapItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RecruitmentAnalyticsResponse(BaseModel):
    """Recruitment intelligence metrics."""

    pipeline_health: str = "EXCELLENT"
    offer_acceptance_rate: float = 84.5
    time_to_hire: str = "18 days"
    candidate_quality_score: float = 4.3
    sources: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PerformanceAnalyticsResponse(BaseModel):
    """Performance intelligence metrics."""

    top_performers_count: int = 14
    low_performers_count: int = 2
    kpi_achievement_pct: float = 91.5
    promotion_readiness_pct: float = 18.0
    items: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WorkforceAnalyticsResponse(BaseModel):
    """Workforce intelligence metrics."""

    utilization_rate: float = 87.5
    productivity_score: float = 94.0
    workforce_health: float = 92.4

    model_config = ConfigDict(from_attributes=True)


class HealthAnalyticsResponse(BaseModel):
    """Employee health analytics metrics."""

    burnout_risk_count: int = 3
    wellbeing_score: float = 88.0
    workload_balance: str = "BALANCED"

    model_config = ConfigDict(from_attributes=True)


class ComplianceAnalyticsResponse(BaseModel):
    """Compliance analytics metrics."""

    compliance_score: float = 92.5
    open_risks_count: int = 4
    missing_docs_count: int = 12
    audit_readiness_pct: float = 94.0

    model_config = ConfigDict(from_attributes=True)


class AttritionPredictionResponse(BaseModel):
    """Attrition prediction metrics."""

    high_risk_count: int = 2
    flight_risk_score: float = 3.8
    department_attrition: list[dict[str, Any]] = Field(default_factory=list)
    items: list[AttritionRiskItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ExecutiveSummaryResponse(BaseModel):
    """Executive summary payload."""

    executive_summary: str
    total_insights: int = 28
    key_insights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    priority_recommendations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# Request Payloads
class AnalyticsGeneratePayload(BaseModel):
    """Payload to trigger new analytics computation."""

    department_id: Optional[uuid.UUID] = None
    date_range: Optional[str] = None


class AnalyticsPredictPayload(BaseModel):
    """Payload to run predictive model simulation."""

    forecast_months: int = Field(6, description="Forecast horizon in months")
    department_id: Optional[uuid.UUID] = None
