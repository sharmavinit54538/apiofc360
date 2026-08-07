"""Pydantic schemas for AI Payroll Insights module APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PayrollDashboardResponse(BaseModel):
    """Payroll Dashboard KPIs."""

    monthly_payroll: float = Field(..., description="Current Month Total Payroll in local currency")
    previous_month_payroll: float = Field(..., description="Previous Month Total Payroll")
    forecast_next_month: float = Field(..., description="Forecasted Next Month Payroll")
    payroll_growth_pct: float = Field(..., description="Payroll Growth Percentage month-over-month")
    payroll_health_score: float = Field(..., description="Overall Payroll Health Index (0-100)")
    total_employees_paid: int = Field(..., description="Total employees disbursed in latest run")
    pending_payroll: float = Field(..., description="Pending un-disbursed payroll amount")
    payroll_processing_status: str = Field("COMPLETED", description="COMPLETED | PROCESSING | DRAFT")

    model_config = ConfigDict(from_attributes=True)


class ForecastDataPoint(BaseModel):
    """Forecast data point for a month or quarter."""

    label: str
    actual_payroll: float = 0.0
    forecast_payroll: float = 0.0
    growth_pct: float = 0.0
    confidence_score: float = 90.0

    model_config = ConfigDict(from_attributes=True)


class PayrollForecastResponse(BaseModel):
    """Payroll Forecast series across next month, quarter, 6m, 12m."""

    period: str = "Next 12 Months"
    actual_payroll: float = 0.0
    forecast_payroll: float = 0.0
    growth_pct: float = 0.0
    confidence_score: float = 92.5
    data: list[ForecastDataPoint] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DepartmentCostItem(BaseModel):
    """Department payroll cost breakdown."""

    department: str
    total_cost: float
    avg_salary: float
    headcount: int
    overtime_cost: float = 0.0
    bonus_cost: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class CostByDepartmentResponse(BaseModel):
    """Cost by Department list."""

    total_payroll_cost: float
    department_costs: list[DepartmentCostItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SalaryBenchmarkItem(BaseModel):
    """Salary Benchmarking record."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    role: str
    experience_years: float = 3.5
    current_salary: float
    company_avg: float
    market_avg: float
    salary_gap: float
    recommendation: str

    model_config = ConfigDict(from_attributes=True)


class SalaryBenchmarkingResponse(BaseModel):
    """Salary Benchmarking analysis list."""

    total_employees_analyzed: int
    items: list[SalaryBenchmarkItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AnomalyItem(BaseModel):
    """Payroll anomaly record."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    issue: str
    severity: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    confidence: float = 90.0
    recommendation: str

    model_config = ConfigDict(from_attributes=True)


class PayrollAnomaliesResponse(BaseModel):
    """Payroll anomaly detection list."""

    total_anomalies: int
    anomalies: list[AnomalyItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class FraudFlagItem(BaseModel):
    """Fraud detection flag record."""

    fraud_type: str = Field(..., description="GHOST_EMPLOYEE | DUPLICATE_BANK_ACCOUNT | DUPLICATE_PAN | FAKE_OVERTIME | UNUSUAL_SALARY_INCREASE")
    risk_level: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    employee_id: uuid.UUID
    employee_name: str
    department: str
    description: str
    recommendation: str

    model_config = ConfigDict(from_attributes=True)


class FraudDetectionResponse(BaseModel):
    """Payroll fraud detection analysis list."""

    total_fraud_flags: int
    fraud_flags: list[FraudFlagItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PayrollHealthScoreResponse(BaseModel):
    """Payroll Health Score (0-100) and factors."""

    health_score: float = Field(..., ge=0.0, le=100.0)
    accuracy_score: float = 98.0
    processing_time_score: float = 95.0
    error_rate: float = 0.5
    failed_payroll_count: int = 0
    compliance_score: float = 96.0
    tax_accuracy_score: float = 97.5
    insights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CostAnalysisResponse(BaseModel):
    """Cost Analysis summary."""

    total_payroll_cost: float
    cost_trend: list[dict[str, Any]] = Field(default_factory=list)
    salary_distribution: list[dict[str, Any]] = Field(default_factory=list)
    cost_drivers: list[str] = Field(default_factory=list)
    payroll_breakdown: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class PayrollAnalyticsResponse(BaseModel):
    """Payroll Analytics overview."""

    monthly_trend: list[dict[str, Any]] = Field(default_factory=list)
    department_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    cost_distribution: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeePayrollDetailResponse(BaseModel):
    """Employee payroll details."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    designation: str
    ctc: float
    monthly_gross: float
    monthly_net: float
    bank_account_masked: Optional[str] = None
    pan_masked: Optional[str] = None
    payslip_count: int = 0

    model_config = ConfigDict(from_attributes=True)


# Request Payloads
class PayrollForecastPayload(BaseModel):
    """Payload to request payroll forecast."""

    months_ahead: int = 12
    department_id: Optional[uuid.UUID] = None


class AnalyzePayrollPayload(BaseModel):
    """Payload to analyze a payroll run."""

    payroll_run_id: Optional[uuid.UUID] = None


class DetectAnomaliesPayload(BaseModel):
    """Payload to detect payroll anomalies."""

    department_id: Optional[uuid.UUID] = None


class DetectFraudPayload(BaseModel):
    """Payload to detect payroll fraud."""

    department_id: Optional[uuid.UUID] = None
