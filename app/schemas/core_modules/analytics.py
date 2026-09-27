"""Pydantic schemas for Analytics Core Module."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnalyticsFilterParams(BaseModel):
    # inferred field — confirm with product/spec owner
    period_type: str = Field("monthly", description="monthly | yearly | daily | quarterly")
    # inferred field — confirm with product/spec owner
    from_date: Optional[date] = None
    # inferred field — confirm with product/spec owner
    to_date: Optional[date] = None
    # inferred field — confirm with product/spec owner
    department: Optional[str] = None
    # inferred field — confirm with product/spec owner
    designation: Optional[str] = None


class MetricSummaryResponse(BaseModel):
    # inferred field — confirm with product/spec owner
    metric: str
    # inferred field — confirm with product/spec owner
    total: float | int
    # inferred field — confirm with product/spec owner
    unit: str = ""
    # inferred field — confirm with product/spec owner
    trend_percentage: Optional[float] = 0.0
    # inferred field — confirm with product/spec owner
    breakdown: Dict[str, Any] = Field(default_factory=dict)
    # inferred field — confirm with product/spec owner
    timeline: List[Dict[str, Any]] = Field(default_factory=list)


class AnalyticsDashboardResponse(BaseModel):
    # inferred field — confirm with product/spec owner
    headcount: int
    # inferred field — confirm with product/spec owner
    active_employees: int
    # inferred field — confirm with product/spec owner
    today_attendance_rate: float
    # inferred field — confirm with product/spec owner
    open_jobs: int
    # inferred field — confirm with product/spec owner
    total_payroll_cost: float
    # inferred field — confirm with product/spec owner
    avg_performance_rating: float
    # inferred field — confirm with product/spec owner
    attrition_rate: float
    # inferred field — confirm with product/spec owner
    metrics: Dict[str, Any] = Field(default_factory=dict)
