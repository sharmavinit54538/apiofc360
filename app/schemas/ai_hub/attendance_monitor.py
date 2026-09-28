"""Schemas for AI Hub Attendance Monitor module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class AttendanceMonitorOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attendanceHealthScore: float
    totalAttendancePercentage: float
    totalAnomalies: int
    lateArrivals: int
    overtimeHours: float
    todayPresentEmployees: int
    todayAbsentEmployees: int


class AnalyzeAttendanceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    startDate: str
    endDate: str
    department: Optional[str] = None


class AttendanceAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    period: str
    department: Optional[str] = None
    attendanceRate: float
    anomaliesCount: int
    lateArrivalsCount: int
    overtimeHours: float
    summary: str
    insights: list[str] = Field(default_factory=list)


class AttendanceAnomalyItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    employeeId: str
    employeeName: str
    department: str
    date: str
    anomalyType: str
    severity: str
    description: str


class AttendanceAnomaliesPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AttendanceAnomalyItem]
    total: int
    page: int
    limit: int
    pages: int
