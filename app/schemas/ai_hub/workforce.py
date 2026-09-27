"""Schemas for AI Hub Workforce Insights and Workforce Planning modules."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


# -------------------------------------------------------------------------
# Workforce Insights
# -------------------------------------------------------------------------

class WorkforceInsightsOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalEmployees: int
    utilizationRate: float
    productivityScore: float
    workforceHealthScore: float
    departmentsCount: int
    topPerformingDepartment: str
    underCapacityCount: int


class AnalyzeWorkforceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: Optional[str] = None
    timeframe: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)


class WorkforceAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: Optional[str] = None
    timeframe: Optional[str] = None
    capacityUtilizationPct: float
    productivityIndex: float
    burnoutRiskFactor: float
    keyMetrics: dict[str, Any] = Field(default_factory=dict)
    optimizationOpportunities: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------------
# Workforce Planning
# -------------------------------------------------------------------------

class WorkforcePlanningOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    currentHeadcount: int
    projectedHeadcount: int
    requiredHiringCount: int
    estimatedHiringBudget: float
    confidenceScore: float
    departmentBreakdown: list[dict[str, Any]] = Field(default_factory=list)


class ForecastWorkforceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    horizonMonths: int = 12
    growthRate: float = 0.1
    departments: list[str] = Field(default_factory=list)


class DepartmentForecastItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: str
    currentHeadcount: int
    forecastHeadcount: int
    netNewHiresNeeded: int
    estimatedCost: float


class ForecastWorkforceResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    horizonMonths: int
    overallGrowthRate: float
    totalCurrentHeadcount: int
    totalForecastHeadcount: int
    totalNewHiresNeeded: int
    totalEstimatedBudget: float
    departmentForecasts: list[DepartmentForecastItem] = Field(default_factory=list)


class HeadcountPlanningRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    growthTarget: float
    budgetCap: Optional[float] = None


class HeadcountPlanningResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    growthTarget: float
    budgetCap: Optional[float] = None
    allocatedHeadcount: int
    projectedSpend: float
    budgetStatus: str  # WITHIN_BUDGET, EXCEEDED, OPTIMAL
    allocationsByDepartment: list[dict[str, Any]] = Field(default_factory=list)
    hiringPhases: list[dict[str, Any]] = Field(default_factory=list)
