"""Schemas for AI Hub Payroll Insights module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class PayrollInsightsOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    monthlyPayrollCost: float
    forecastPayrollCost: float
    overtimeCost: float
    totalAnomalies: int
    healthScore: float
    complianceScore: float
    activeEmployeesCount: int


class AnalyzePayrollRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cycle: str
    department: Optional[str] = None
    thresholdPercentage: float = 5.0


class PayrollAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cycle: str
    department: Optional[str] = None
    totalPayrollCost: float
    variancePercentage: float
    flaggedComponentsCount: int
    costDrivers: list[str] = Field(default_factory=list)
    breakdown: dict[str, float] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class PayrollAnomalyItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    employeeId: str
    employeeName: str
    department: str
    anomalyType: str
    expectedAmount: float
    actualAmount: float
    variancePct: float
    severity: str
    explanation: str


class PayrollAnomaliesPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[PayrollAnomalyItem]
    total: int
    page: int
    limit: int
    pages: int


class TaxAuditRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    taxYear: int
    quarter: Optional[str] = None
    jurisdiction: Optional[str] = None


class TaxAuditResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    taxYear: int
    quarter: Optional[str] = None
    jurisdiction: Optional[str] = None
    complianceScore: float
    tdsReconciledPct: float
    totalTaxDeducted: float
    discrepanciesCount: int
    discrepancies: list[dict[str, Any]] = Field(default_factory=list)
    auditReadiness: str  # HIGH, MEDIUM, LOW
    recommendations: list[str] = Field(default_factory=list)
