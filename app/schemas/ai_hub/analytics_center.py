"""Schemas for AI Hub Analytics Center module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class AnalyticsCenterOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalAiInsights: int = 28
    workforceHealthScore: float = 92.4
    attritionRiskPct: float = 3.8
    hiringEfficiencyPct: float = 88.5
    payrollHealthPct: float = 96.0
    complianceScore: float = 92.5
    activeEmployees: int = 0
    openPositions: int = 0
    kpis: list[dict[str, Any]] = Field(default_factory=list)


class AttritionDepartmentItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: str
    attritionPct: float
    headcount: int = 0
    riskLevel: str = "LOW"


class AttritionRiskProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    employeeId: str
    employeeName: Optional[str] = None
    department: str
    riskScore: float
    riskFactors: list[str] = Field(default_factory=list)


class AttritionAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    highRiskCount: int
    flightRiskScore: float
    departmentAttrition: list[AttritionDepartmentItem] = Field(default_factory=list)
    topRiskProfiles: list[AttritionRiskProfile] = Field(default_factory=list)
    mitigationRecommendations: list[str] = Field(default_factory=list)


class DiversityBreakdownItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    count: int
    percentage: float


class DiversityAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalEmployees: int
    genderDiversity: list[DiversityBreakdownItem] = Field(default_factory=list)
    departmentDiversity: list[DiversityBreakdownItem] = Field(default_factory=list)
    leadershipDiversityPct: float = 40.0
    diversityScore: float = 85.0
    insights: list[str] = Field(default_factory=list)


class ExecutiveSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalInsights: int
    executiveSummary: str
    keyInsights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AnalyzeFilters(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: Optional[str] = None
    location: Optional[str] = None


class AnalyzeAnalyticsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    timeframe: str
    filters: AnalyzeFilters = Field(default_factory=AnalyzeFilters)


class AnalyzeAnalyticsResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    timeframe: str
    filtersApplied: dict[str, Any] = Field(default_factory=dict)
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
