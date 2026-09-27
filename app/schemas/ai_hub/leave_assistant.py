"""Schemas for AI Hub Leave Assistant module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class LeaveAssistantOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalLeaves: int
    pendingApprovals: int
    conflictsDetected: int
    averageLeaveDays: float
    teamAvailabilityPct: float
    peakLeaveRisk: str = "LOW"


class AnalyzeLeaveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timeframe: str
    department: Optional[str] = None


class LeaveAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timeframe: str
    department: Optional[str] = None
    totalRequests: int
    approvalRate: float
    avgDurationDays: float
    peakMonths: list[str] = Field(default_factory=list)
    topLeaveTypes: list[dict[str, Any]] = Field(default_factory=list)
    conflictsCount: int
    recommendations: list[str] = Field(default_factory=list)


class ForecastLeaveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    startDate: str
    endDate: str
    department: Optional[str] = None


class LeaveForecastDataPoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    periodLabel: str
    expectedLeaveDays: float
    riskLevel: str
    affectedDepartment: Optional[str] = None


class LeaveForecastResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    startDate: str
    endDate: str
    department: Optional[str] = None
    totalExpectedDays: float
    projectedImpactLevel: str
    forecast: list[LeaveForecastDataPoint] = Field(default_factory=list)
    coverageRecommendations: list[str] = Field(default_factory=list)
