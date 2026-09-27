"""Schemas for AI Hub Employee Health module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class EmployeeHealthOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overallHealthScore: float
    burnoutRiskIndex: float
    workloadCapacityPct: float
    totalOvertimeHours: float
    stressIndex: float
    highRiskEmployeesCount: int


class AnalyzeEmployeeHealthRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: Optional[str] = None
    factors: list[str] = Field(default_factory=list)


class EmployeeHealthAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: Optional[str] = None
    analyzedFactors: list[str] = Field(default_factory=list)
    healthIndex: float
    burnoutRiskLevel: str  # LOW, MEDIUM, HIGH
    overtimeAlertsCount: int
    recommendations: list[str] = Field(default_factory=list)
    departmentInsights: list[dict[str, Any]] = Field(default_factory=list)


class WellnessScoreResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    wellbeingScore: float
    attendanceFactor: float
    leaveUsageFactor: float
    workloadFactor: float
    overtimeFactor: float
    stressSignalsFactor: float
    insights: list[str] = Field(default_factory=list)
    actionItems: list[str] = Field(default_factory=list)
