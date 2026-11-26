"""Pydantic response schemas for the Payroll Dashboard API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DashboardPeriodInfo(BaseModel):
    """Resolved payroll period metadata for the dashboard."""

    id: str
    company_id: Optional[str] = None
    name: str
    frequency: str = "MONTHLY"
    period_month: int
    period_year: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    processing_date: Optional[str] = None
    payment_date: Optional[str] = None
    pay_date: Optional[str] = None
    status: str
    is_locked: bool = False
    is_current: bool = False
    attendance_locked: bool = False
    attendance_locked_at: Optional[datetime] = None


class DashboardSummaryMetrics(BaseModel):
    """Top-level payroll period KPIs preserving legacy keys + production fields."""

    cycle_month: str
    period_month: int
    period_year: int
    total_employees: int = 0
    eligible_employees: int = 0
    included_employees: int = 0
    processed_count: int = 0
    paid_count: int = 0
    pending_count: int = 0
    on_hold_count: int = 0
    failed_count: int = 0
    total_gross: float = 0.0
    total_deductions: float = 0.0
    total_net: float = 0.0
    employer_contributions: Optional[float] = None
    total_payroll_cost: Optional[float] = None
    average_gross_salary: Optional[float] = None
    average_net_salary: Optional[float] = None
    total_gross_paise: int = 0
    total_deductions_paise: int = 0
    total_net_paise: int = 0
    employer_contributions_paise: Optional[int] = None
    total_payroll_cost_paise: Optional[int] = None
    currency: str = "INR"
    status: str  # COMPLETED | IN_PROGRESS | NOT_STARTED | FAILED


class EmployeeCountsSummary(BaseModel):
    """Disaggregated employee headcounts by lifecycle state."""

    eligible: int = 0
    included: int = 0
    processed: int = 0
    paid: int = 0
    pending: int = 0
    on_hold: int = 0
    failed: int = 0


class EmployerContributionsBreakdown(BaseModel):
    """Verified employer contribution components (null if statutory records absent)."""

    total: Optional[float] = None
    total_paise: Optional[int] = None
    employer_pf: Optional[float] = None
    employer_esi: Optional[float] = None
    employer_lwf: Optional[float] = None
    employer_edli_and_admin: Optional[float] = None
    gratuity_provision: Optional[float] = None
    other_employer: Optional[float] = None


class StatutorySummary(BaseModel):
    """Statutory deductions vs employer contributions & remittance status."""

    employee_deductions_total: float = 0.0
    employer_contributions_total: Optional[float] = None
    total_liability: Optional[float] = None
    remitted_amount: float = 0.0
    pending_liabilities: float = 0.0
    pf_employee: float = 0.0
    pf_employer: float = 0.0
    esi_employee: float = 0.0
    esi_employer: float = 0.0
    pt_total: float = 0.0
    tds_total: float = 0.0
    lwf_total: float = 0.0
    pending_filings_count: int = 0
    overdue_filings_count: int = 0


class PaymentStatusSummary(BaseModel):
    """Bank batch & disbursement state summary for the selected period."""

    total_payable: float = 0.0
    paid_amount: float = 0.0
    pending_amount: float = 0.0
    failed_amount: float = 0.0
    held_amount: float = 0.0
    paid_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    held_count: int = 0
    batch_count: int = 0
    latest_batch_status: Optional[str] = None


class ApprovalSummary(BaseModel):
    """Pending payroll approvals aggregated across real workflow queues."""

    pending_count: int = 0
    runs_pending_approval: int = 0
    variable_inputs_pending: int = 0
    compensation_revisions_pending: int = 0
    attendance_regularizations_pending: int = 0
    leave_requests_pending: int = 0
    approved_runs_count: int = 0
    rejected_runs_count: int = 0
    status: str = "NOT_SUBMITTED"


class ReadinessCheckItem(BaseModel):
    """Single read-only prerequisite check for running payroll."""

    area: str
    status: str  # Ready | Warning | Error
    details: Optional[str] = None


class ReadinessSummary(BaseModel):
    """Aggregated readiness checks for the selected payroll period."""

    items: list[ReadinessCheckItem] = Field(default_factory=list)
    is_ready: bool = True
    blocking_count: int = 0
    warning_count: int = 0


class DashboardIssueItem(BaseModel):
    """Normalized exception / validation issue surfaced on the dashboard."""

    id: str
    type: str  # error | warning
    category: str
    message: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    blocking: bool = False


class DashboardIssuesSummary(BaseModel):
    """Unique validation issues and severity counts for the selected period."""

    errors: list[DashboardIssueItem] = Field(default_factory=list)
    warnings: list[DashboardIssueItem] = Field(default_factory=list)
    unique_employee_count: int = 0
    total_error_count: int = 0
    total_warning_count: int = 0


class DashboardRunSummary(BaseModel):
    """Single payroll run record for active run state & recent run history."""

    id: str
    run_number: Optional[str] = None
    period_id: Optional[str] = None
    period_name: str
    period_month: int
    period_year: int
    status: str
    validation_status: str = "PENDING"
    employee_count: int = 0
    paid_count: int = 0
    failed_payment_count: int = 0
    gross_payroll: float = 0.0
    total_deductions: float = 0.0
    net_payroll: float = 0.0
    employer_contributions: Optional[float] = None
    total_payroll_cost: Optional[float] = None
    is_locked: bool = False
    currency: str = "INR"
    run_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DashboardTrendPoint(BaseModel):
    """Historical monthly payroll cost trend point (chronological)."""

    period_id: Optional[str] = None
    label: str
    month: int
    year: int
    employee_count: int = 0
    gross_payroll: float = 0.0
    total_deductions: float = 0.0
    net_payroll: float = 0.0
    employer_contributions: Optional[float] = None
    total_payroll_cost: Optional[float] = None
    status: str


class PayrollDashboardResponse(BaseModel):
    """Canonical Payroll Dashboard payload returned under APIResponse.data."""

    period: Optional[DashboardPeriodInfo] = None
    summary: DashboardSummaryMetrics
    status: str
    employee_counts: EmployeeCountsSummary = Field(default_factory=EmployeeCountsSummary)
    employer_contributions: EmployerContributionsBreakdown = Field(
        default_factory=EmployerContributionsBreakdown
    )
    statutory_summary: StatutorySummary = Field(default_factory=StatutorySummary)
    payment_summary: PaymentStatusSummary = Field(default_factory=PaymentStatusSummary)
    approval_summary: ApprovalSummary = Field(default_factory=ApprovalSummary)
    readiness: ReadinessSummary = Field(default_factory=ReadinessSummary)
    issues: DashboardIssuesSummary = Field(default_factory=DashboardIssuesSummary)
    active_run: Optional[DashboardRunSummary] = None
    recent_runs: list[DashboardRunSummary] = Field(default_factory=list)
    trends: list[DashboardTrendPoint] = Field(default_factory=list)
    currency: str = "INR"
    last_updated_at: datetime
