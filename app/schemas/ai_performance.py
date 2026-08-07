"""Pydantic schemas for AI Performance Coach module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PerformanceDashboardResponse(BaseModel):
    """Performance Dashboard KPIs."""

    average_performance_score: float = Field(..., description="Organization average performance score (0-5.0 scale)")
    top_performers_count: int = Field(..., description="Count of top performing employees")
    skill_gaps_count: int = Field(..., description="Count of identified skill gaps")
    promotion_picks_count: int = Field(..., description="Count of recommended promotion picks")

    model_config = ConfigDict(from_attributes=True)


class TrendItem(BaseModel):
    """Single performance trend data point."""

    label: str
    score: float = 0.0
    kpi_attainment_pct: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class PerformanceTrendsResponse(BaseModel):
    """Performance Trends data across periods."""

    period: str
    group_by: str = "quarterly"
    data: list[TrendItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class FunctionKpiItem(BaseModel):
    """KPI Attainment metric per department/function."""

    function_name: str
    target_kpi: int = 100
    achieved_kpi: int = 85
    attainment_percentage: float = 85.0
    trend: str = "+5.2%"

    model_config = ConfigDict(from_attributes=True)


class KpiAttainmentResponse(BaseModel):
    """KPI Attainment breakdown by function."""

    functions: list[FunctionKpiItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TopPerformerItem(BaseModel):
    """Top performing entity entry."""

    id: uuid.UUID
    name: str
    department: str
    role_or_title: str
    score: float
    attainment_percentage: float

    model_config = ConfigDict(from_attributes=True)


class TopPerformersResponse(BaseModel):
    """Top Performers breakdown."""

    top_employees: list[TopPerformerItem] = Field(default_factory=list)
    top_departments: list[dict[str, Any]] = Field(default_factory=list)
    top_managers: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeePerformanceResponse(BaseModel):
    """Detailed employee performance scores."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    manager_name: str = "Manager"
    overall_score: float = 4.2
    productivity_score: float = 88.0
    attendance_score: float = 95.0
    quality_score: float = 86.0
    behavior_score: float = 90.0
    leadership_score: float = 84.0
    communication_score: float = 88.0
    quarter: str = "Q3"
    year: int = 2026

    model_config = ConfigDict(from_attributes=True)


class SkillGapItem(BaseModel):
    """Skill gap entry."""

    employee_id: Optional[uuid.UUID] = None
    employee_name: Optional[str] = None
    department: str
    role: str
    required_skill: str
    current_skill_level: str = "Intermediate"
    missing_skill: str
    priority: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    training_required: str

    model_config = ConfigDict(from_attributes=True)


class SkillGapsResponse(BaseModel):
    """Skill Gap Analysis results."""

    total_missing_skills: int
    items: list[SkillGapItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PromotionRecommendationItem(BaseModel):
    """AI Promotion recommendation record."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    current_position: str
    recommended_position: str
    reason: str
    performance_history: str = "Consistently exceeds quarterly targets"
    leadership_score: float = 85.0
    confidence_score: float = 92.0
    promotion_readiness: str = Field("READY_NOW", description="READY_NOW | READY_IN_6M | NEEDS_DEVELOPMENT")
    risk_factors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PromotionRecommendationsResponse(BaseModel):
    """Promotion Recommendations breakdown."""

    total_picks: int
    items: list[PromotionRecommendationItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CoachingSuggestionItem(BaseModel):
    """Personalized AI Coaching suggestion."""

    employee_id: uuid.UUID
    employee_name: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    learning_path: list[str] = Field(default_factory=list)
    courses: list[dict[str, str]] = Field(default_factory=list)
    manager_suggestions: list[str] = Field(default_factory=list)
    improvement_areas: list[str] = Field(default_factory=list)
    next_review_date: str = "2026-09-30"

    model_config = ConfigDict(from_attributes=True)


class CoachingSuggestionsResponse(BaseModel):
    """Coaching Suggestions breakdown."""

    total_suggestions: int
    items: list[CoachingSuggestionItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PerformanceAnalyticsResponse(BaseModel):
    """Overall Performance Analytics breakdown."""

    overall_average: float = 4.15
    department_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    quarterly_trend: list[dict[str, Any]] = Field(default_factory=list)
    kpi_completion_rate: float = 87.5

    model_config = ConfigDict(from_attributes=True)


# Request Models
class EvaluatePerformanceRequest(BaseModel):
    """Evaluate performance payload."""

    review_id: uuid.UUID


class GenerateCoachingRequest(BaseModel):
    """Generate coaching suggestions payload."""

    employee_id: uuid.UUID


class GeneratePromotionRequest(BaseModel):
    """Generate promotion recommendation payload."""

    employee_id: uuid.UUID


class SkillGapAnalysisRequest(BaseModel):
    """Request skill gap analysis payload."""

    department_id: Optional[uuid.UUID] = None
    employee_id: Optional[uuid.UUID] = None
