"""Pydantic v2 schemas for the complete Payroll module.

All request/response schemas for all 15 sub-modules live here.
Imported by: app/api/v2/payroll_api.py

Request / Response models for all 15 sub-modules.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _MoneyDecimal(Decimal):
    """Alias to mark intentional Decimal (not float) money fields."""


# ---------------------------------------------------------------------------
# 1. PAY CYCLE
# ---------------------------------------------------------------------------

class PayCycleCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2020, le=2100)
    remarks: Optional[str] = None


class PayCycleUpdate(BaseModel):
    remarks: Optional[str] = None
    status: Optional[str] = None


class PayCycleResponse(BaseModel):
    id: uuid.UUID
    company_id: Optional[uuid.UUID]
    period_month: int
    period_year: int
    period_label: str
    status: str
    total_employees: int
    total_gross: float
    total_deductions: float
    total_net: float
    total_reimbursements: float
    total_bonuses: float
    locked_at: Optional[str]
    approved_at: Optional[str]
    disbursed_at: Optional[str]
    remarks: Optional[str]
    validation_flags: Optional[dict]
    created_at: str

    @classmethod
    def from_orm(cls, cycle: Any) -> "PayCycleResponse":
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return cls(
            id=cycle.id,
            company_id=cycle.company_id,
            period_month=cycle.period_month,
            period_year=cycle.period_year,
            period_label=f"{month_names[cycle.period_month - 1]}-{cycle.period_year}",
            status=cycle.status,
            total_employees=cycle.total_employees,
            total_gross=float(cycle.total_gross),
            total_deductions=float(cycle.total_deductions),
            total_net=float(cycle.total_net),
            total_reimbursements=float(cycle.total_reimbursements),
            total_bonuses=float(cycle.total_bonuses),
            locked_at=cycle.locked_at.isoformat() if cycle.locked_at else None,
            approved_at=cycle.approved_at.isoformat() if cycle.approved_at else None,
            disbursed_at=cycle.disbursed_at.isoformat() if cycle.disbursed_at else None,
            remarks=cycle.remarks,
            validation_flags=cycle.validation_flags,
            created_at=cycle.created_at.isoformat(),
        )


class PayCycleListResponse(BaseModel):
    page: int
    limit: int
    total: int
    items: List[PayCycleResponse]


# ---------------------------------------------------------------------------
# 2. AUDIT LOG
# ---------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: Optional[uuid.UUID]
    action: str
    actor_id: Optional[uuid.UUID]
    actor_role: Optional[str]
    old_status: Optional[str]
    new_status: Optional[str]
    reason: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, log: Any) -> "AuditLogResponse":
        return cls(
            id=log.id,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            action=log.action,
            actor_id=log.actor_id,
            actor_role=log.actor_role,
            old_status=log.old_status,
            new_status=log.new_status,
            reason=log.reason,
            created_at=log.created_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# 3. OVERTIME
# ---------------------------------------------------------------------------

class OvertimePolicyCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=1, max_length=100)
    applicable_role: Optional[str] = None
    applicable_grade: Optional[str] = None
    rate_multiplier: Decimal = Field(Decimal("1.5"), ge=Decimal("1.0"), le=Decimal("5.0"))
    max_ot_hours_per_month: Optional[Decimal] = None


class OvertimePolicyUpdate(BaseModel):
    name: Optional[str] = None
    applicable_role: Optional[str] = None
    applicable_grade: Optional[str] = None
    rate_multiplier: Optional[Decimal] = None
    max_ot_hours_per_month: Optional[Decimal] = None
    is_active: Optional[bool] = None


class OvertimePolicyResponse(BaseModel):
    id: uuid.UUID
    company_id: Optional[uuid.UUID]
    name: str
    applicable_role: Optional[str]
    applicable_grade: Optional[str]
    rate_multiplier: float
    max_ot_hours_per_month: Optional[float]
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, p: Any) -> "OvertimePolicyResponse":
        return cls(
            id=p.id, company_id=p.company_id, name=p.name,
            applicable_role=p.applicable_role, applicable_grade=p.applicable_grade,
            rate_multiplier=float(p.rate_multiplier),
            max_ot_hours_per_month=float(p.max_ot_hours_per_month) if p.max_ot_hours_per_month else None,
            is_active=p.is_active, created_at=p.created_at.isoformat(),
        )


class OvertimeEntryCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    employee_id: uuid.UUID
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2020, le=2100)
    ot_hours: Decimal = Field(..., ge=0)
    ot_rate_per_hour: Decimal = Field(..., ge=0)
    remarks: Optional[str] = None


class OvertimeEntryAdjust(BaseModel):
    adjusted_hours: Decimal = Field(..., ge=0)
    remarks: Optional[str] = None


class OvertimeEntryResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    period_month: int
    period_year: int
    ot_hours: float
    adjusted_hours: Optional[float]
    effective_hours: float
    ot_rate_per_hour: float
    ot_amount: float
    status: str
    remarks: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, e: Any) -> "OvertimeEntryResponse":
        effective = float(e.adjusted_hours if e.adjusted_hours is not None else e.ot_hours)
        return cls(
            id=e.id, employee_id=e.employee_id,
            period_month=e.period_month, period_year=e.period_year,
            ot_hours=float(e.ot_hours),
            adjusted_hours=float(e.adjusted_hours) if e.adjusted_hours is not None else None,
            effective_hours=effective,
            ot_rate_per_hour=float(e.ot_rate_per_hour),
            ot_amount=float(e.ot_amount),
            status=e.status, remarks=e.remarks,
            created_at=e.created_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# 4. BONUSES & INCENTIVES
# ---------------------------------------------------------------------------

class BonusPlanCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=1, max_length=150)
    plan_type: str = Field("SPOT", pattern="^(SPOT|RECURRING)$")
    description: Optional[str] = None
    eligibility_scope: str = Field("ALL", pattern="^(ALL|EMPLOYEE|DEPARTMENT|ROLE|GRADE)$")
    eligible_ids: Optional[List[str]] = None
    default_amount: Optional[Decimal] = None
    recurrence_months: Optional[int] = None
    requires_approval: bool = True


class BonusPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    eligibility_scope: Optional[str] = None
    eligible_ids: Optional[List[str]] = None
    default_amount: Optional[Decimal] = None
    requires_approval: Optional[bool] = None
    is_active: Optional[bool] = None


class BonusPlanResponse(BaseModel):
    id: uuid.UUID
    company_id: Optional[uuid.UUID]
    name: str
    plan_type: str
    description: Optional[str]
    eligibility_scope: str
    default_amount: Optional[float]
    recurrence_months: Optional[int]
    requires_approval: bool
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, p: Any) -> "BonusPlanResponse":
        return cls(
            id=p.id, company_id=p.company_id, name=p.name, plan_type=p.plan_type,
            description=p.description, eligibility_scope=p.eligibility_scope,
            default_amount=float(p.default_amount) if p.default_amount else None,
            recurrence_months=p.recurrence_months,
            requires_approval=p.requires_approval, is_active=p.is_active,
            created_at=p.created_at.isoformat(),
        )


class BonusAwardCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    employee_id: uuid.UUID
    bonus_plan_id: Optional[uuid.UUID] = None
    amount: Decimal = Field(..., ge=0)
    reason: Optional[str] = None


class BonusAwardResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    bonus_plan_id: Optional[uuid.UUID]
    pay_cycle_id: Optional[uuid.UUID]
    amount: float
    reason: Optional[str]
    status: str
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, a: Any) -> "BonusAwardResponse":
        return cls(
            id=a.id, employee_id=a.employee_id, bonus_plan_id=a.bonus_plan_id,
            pay_cycle_id=a.pay_cycle_id, amount=float(a.amount), reason=a.reason,
            status=a.status, approved_by=a.approved_by,
            approved_at=a.approved_at.isoformat() if a.approved_at else None,
            rejection_reason=a.rejection_reason, created_at=a.created_at.isoformat(),
        )


class ApprovalAction(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# 5. DEDUCTIONS
# ---------------------------------------------------------------------------

class DeductionCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    employee_id: uuid.UUID
    pay_cycle_id: Optional[uuid.UUID] = None
    deduction_type: str = Field(..., description="PF|ESI|PT|LWF|TDS|LOAN_EMI|ADVANCE|VOLUNTARY|ONE_OFF")
    name: str = Field(..., min_length=1, max_length=150)
    amount: Decimal = Field(..., ge=0)
    is_recurring: bool = False
    source_id: Optional[uuid.UUID] = None
    remarks: Optional[str] = None


class DeductionUpdate(BaseModel):
    amount: Optional[Decimal] = None
    is_recurring: Optional[bool] = None
    remarks: Optional[str] = None


class DeductionResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    pay_cycle_id: Optional[uuid.UUID]
    deduction_type: str
    name: str
    amount: float
    is_recurring: bool
    source_id: Optional[uuid.UUID]
    remarks: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, d: Any) -> "DeductionResponse":
        return cls(
            id=d.id, employee_id=d.employee_id, pay_cycle_id=d.pay_cycle_id,
            deduction_type=d.deduction_type, name=d.name, amount=float(d.amount),
            is_recurring=d.is_recurring, source_id=d.source_id, remarks=d.remarks,
            created_at=d.created_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# 6. ADVANCES & LOANS
# ---------------------------------------------------------------------------

class AdvanceLoanCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    employee_id: uuid.UUID
    loan_type: str = Field("ADVANCE", pattern="^(ADVANCE|LOAN)$")
    principal_amount: Decimal = Field(..., ge=0)
    emi_amount: Decimal = Field(..., ge=0)
    total_installments: int = Field(..., ge=1)
    start_from_month: int = Field(..., ge=1, le=12)
    start_from_year: int = Field(..., ge=2020, le=2100)
    reason: Optional[str] = None


class AdvanceLoanResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    loan_type: str
    principal_amount: float
    outstanding_balance: float
    emi_amount: float
    total_installments: int
    installments_paid: int
    start_from_month: int
    start_from_year: int
    status: str
    reason: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, l: Any) -> "AdvanceLoanResponse":
        return cls(
            id=l.id, employee_id=l.employee_id, loan_type=l.loan_type,
            principal_amount=float(l.principal_amount),
            outstanding_balance=float(l.outstanding_balance),
            emi_amount=float(l.emi_amount),
            total_installments=l.total_installments, installments_paid=l.installments_paid,
            start_from_month=l.start_from_month, start_from_year=l.start_from_year,
            status=l.status, reason=l.reason, created_at=l.created_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# 7. REIMBURSEMENTS
# ---------------------------------------------------------------------------

class ReimbursementCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    employee_id: uuid.UUID
    category: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., ge=0)
    description: Optional[str] = None
    receipt_url: Optional[str] = None
    claim_date: date = Field(default_factory=date.today)
    payout_mode: str = Field("CYCLE", pattern="^(CYCLE|STANDALONE)$")


class ReimbursementResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    pay_cycle_id: Optional[uuid.UUID]
    category: str
    amount: float
    description: Optional[str]
    receipt_url: Optional[str]
    claim_date: str
    status: str
    payout_mode: str
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, r: Any) -> "ReimbursementResponse":
        return cls(
            id=r.id, employee_id=r.employee_id, pay_cycle_id=r.pay_cycle_id,
            category=r.category, amount=float(r.amount), description=r.description,
            receipt_url=r.receipt_url, claim_date=r.claim_date.isoformat(),
            status=r.status, payout_mode=r.payout_mode, approved_by=r.approved_by,
            approved_at=r.approved_at.isoformat() if r.approved_at else None,
            rejection_reason=r.rejection_reason, created_at=r.created_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# 8. BANK TRANSFERS
# ---------------------------------------------------------------------------

class BankAdviceFileResponse(BaseModel):
    id: uuid.UUID
    pay_cycle_id: uuid.UUID
    file_name: str
    file_format: str
    total_amount: float
    total_records: int
    status: str
    generated_at: str

    @classmethod
    def from_orm(cls, f: Any) -> "BankAdviceFileResponse":
        return cls(
            id=f.id, pay_cycle_id=f.pay_cycle_id, file_name=f.file_name,
            file_format=f.file_format, total_amount=float(f.total_amount),
            total_records=f.total_records, status=f.status,
            generated_at=f.generated_at.isoformat(),
        )


class DisbursementStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(SUCCESS|FAILED|PENDING)$")
    transaction_ref: Optional[str] = None
    failure_reason: Optional[str] = None


class DisbursementResponse(BaseModel):
    id: uuid.UUID
    advice_file_id: uuid.UUID
    employee_id: uuid.UUID
    bank_account_number: Optional[str]
    bank_ifsc: Optional[str]
    amount: float
    status: str
    transaction_ref: Optional[str]
    failure_reason: Optional[str]
    disbursed_at: Optional[str]

    @classmethod
    def from_orm(cls, d: Any) -> "DisbursementResponse":
        return cls(
            id=d.id, advice_file_id=d.advice_file_id, employee_id=d.employee_id,
            bank_account_number=d.bank_account_number, bank_ifsc=d.bank_ifsc,
            amount=float(d.amount), status=d.status, transaction_ref=d.transaction_ref,
            failure_reason=d.failure_reason,
            disbursed_at=d.disbursed_at.isoformat() if d.disbursed_at else None,
        )


# ---------------------------------------------------------------------------
# 9. COMPLIANCE
# ---------------------------------------------------------------------------

class ComplianceObligationCreate(BaseModel):
    company_id: Optional[uuid.UUID] = None
    pay_cycle_id: Optional[uuid.UUID] = None
    obligation_type: str = Field(..., description="PF|ESI|PT|LWF|GRATUITY|TDS")
    period_label: str = Field(..., min_length=1, max_length=20)
    due_date: date
    amount_due: Decimal = Field(Decimal("0"), ge=0)
    remarks: Optional[str] = None


class ComplianceObligationUpdate(BaseModel):
    status: Optional[str] = None
    amount_due: Optional[Decimal] = None
    remarks: Optional[str] = None


class ComplianceObligationResponse(BaseModel):
    id: uuid.UUID
    company_id: Optional[uuid.UUID]
    pay_cycle_id: Optional[uuid.UUID]
    obligation_type: str
    period_label: str
    due_date: str
    amount_due: float
    status: str
    filed_at: Optional[str]
    remarks: Optional[str]
    created_at: str

    @classmethod
    def from_orm(cls, o: Any) -> "ComplianceObligationResponse":
        return cls(
            id=o.id, company_id=o.company_id, pay_cycle_id=o.pay_cycle_id,
            obligation_type=o.obligation_type, period_label=o.period_label,
            due_date=o.due_date.isoformat(), amount_due=float(o.amount_due),
            status=o.status,
            filed_at=o.filed_at.isoformat() if o.filed_at else None,
            remarks=o.remarks, created_at=o.created_at.isoformat(),
        )


class ComplianceDocumentCreate(BaseModel):
    document_name: str = Field(..., min_length=1, max_length=255)
    document_url: str = Field(..., min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# 10. TAX MANAGEMENT
# ---------------------------------------------------------------------------

class TaxDeclarationProofCreate(BaseModel):
    section: str = Field(..., description="80C|80D|80CCD1B|24B|OTHER")
    document_name: str = Field(..., min_length=1, max_length=255)
    document_url: str = Field(..., min_length=1, max_length=500)
    amount_claimed: Decimal = Field(Decimal("0"), ge=0)


class TaxDeclarationProofResponse(BaseModel):
    id: uuid.UUID
    declaration_id: uuid.UUID
    employee_id: uuid.UUID
    section: str
    document_name: str
    document_url: str
    amount_claimed: float
    verified_by_hr: bool
    uploaded_at: str

    @classmethod
    def from_orm(cls, p: Any) -> "TaxDeclarationProofResponse":
        return cls(
            id=p.id, declaration_id=p.declaration_id, employee_id=p.employee_id,
            section=p.section, document_name=p.document_name, document_url=p.document_url,
            amount_claimed=float(p.amount_claimed), verified_by_hr=p.verified_by_hr,
            uploaded_at=p.uploaded_at.isoformat(),
        )


class TDSSummaryResponse(BaseModel):
    employee_id: uuid.UUID
    financial_year: str
    annual_taxable_income: float
    total_deductions: float
    net_taxable_income: float
    estimated_tds: float
    tds_per_month: float
    regime: str


class Form16Response(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    financial_year: str
    total_gross: float
    total_deductions: float
    net_taxable: float
    total_tds: float
    form16_data: dict  # Structured Form-16 sections


# ---------------------------------------------------------------------------
# 11. PAYROLL PROCESSING SUMMARY
# ---------------------------------------------------------------------------

class ProcessingSummaryResponse(BaseModel):
    pay_cycle_id: uuid.UUID
    period_label: str
    status: str
    headcount: int
    total_gross: float
    total_deductions: float
    total_net: float
    total_reimbursements: float
    total_bonuses: float
    validation_flags: Optional[dict]
    department_breakdown: List[dict]


# ---------------------------------------------------------------------------
# 12. AI INSIGHTS DASHBOARD
# ---------------------------------------------------------------------------

class PayrollDashboardResponse(BaseModel):
    monthly_total: float
    next_month_forecast: float
    anomaly_count: int
    health_score: float
    forecast_series: List[dict]   # [{month, actual, forecast}]
    cost_by_department: List[dict]  # [{department, cost}]


class ForecastResponse(BaseModel):
    forecast_months: List[dict]  # [{month_label, predicted_cost, confidence}]
    model_note: str


class BenchmarkResponse(BaseModel):
    department: str
    role: str
    avg_salary_internal: float
    p25: float
    p50: float
    p75: float
    market_reference: Optional[float]


class HealthScoreResponse(BaseModel):
    score: float
    grade: str
    signals: dict  # {on_time_pct, accuracy_pct, anomaly_rate, coverage_pct}
    recent_cycles_evaluated: int


# ---------------------------------------------------------------------------
# Inline schemas (previously in payroll_api.py)
# ---------------------------------------------------------------------------

class SalaryStructureCreate(BaseModel):
    employee_id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    annual_ctc: Decimal = Field(..., ge=0)
    basic_monthly: Decimal = Field(..., ge=0)
    hra_monthly: Decimal = Field(Decimal("0"), ge=0)
    conveyance_monthly: Decimal = Field(Decimal("0"), ge=0)
    special_allowance_monthly: Decimal = Field(Decimal("0"), ge=0)
    other_allowances: Optional[dict] = None
    annual_bonus: Decimal = Field(Decimal("0"), ge=0)
    is_metro_city: bool = False
    rent_paid_monthly: Optional[Decimal] = None
    tax_regime: str = Field("NEW", pattern="^(NEW|OLD)$")
    effective_from: date


class SalaryStructureUpdate(BaseModel):
    annual_ctc: Optional[Decimal] = None
    basic_monthly: Optional[Decimal] = None
    hra_monthly: Optional[Decimal] = None
    conveyance_monthly: Optional[Decimal] = None
    special_allowance_monthly: Optional[Decimal] = None
    other_allowances: Optional[dict] = None
    annual_bonus: Optional[Decimal] = None
    is_metro_city: Optional[bool] = None
    rent_paid_monthly: Optional[Decimal] = None
    tax_regime: Optional[str] = None
    effective_from: Optional[date] = None


class AttendanceInputCreate(BaseModel):
    employee_id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2020, le=2100)
    paid_days: Decimal = Field(..., ge=0, le=31)
    lop_days: Decimal = Field(Decimal("0"), ge=0, le=31)
    arrears: Decimal = Field(Decimal("0"), ge=0)
    one_time_bonus: Decimal = Field(Decimal("0"), ge=0)
    remarks: Optional[str] = None


class AttendanceInputUpdate(BaseModel):
    paid_days: Optional[Decimal] = None
    lop_days: Optional[Decimal] = None
    arrears: Optional[Decimal] = None
    one_time_bonus: Optional[Decimal] = None
    remarks: Optional[str] = None


class PayslipPaymentUpdate(BaseModel):
    payment_status: str = Field(..., pattern="^(PAID|HOLD|FAILED|PENDING)$")
    payment_reference: Optional[str] = None
    payment_date: Optional[date] = None


class StatutoryConfigUpsert(BaseModel):
    company_id: Optional[uuid.UUID] = None
    pf_enabled: bool = True
    employee_pf_rate: Decimal = Field(Decimal("0.12"), ge=0, le=1)
    employer_pf_rate: Decimal = Field(Decimal("0.12"), ge=0, le=1)
    pf_wage_ceiling: Decimal = Field(Decimal("15000"), ge=0)
    pf_on_full_basic: bool = False
    esi_enabled: bool = True
    employee_esi_rate: Decimal = Field(Decimal("0.0075"), ge=0, le=1)
    employer_esi_rate: Decimal = Field(Decimal("0.0325"), ge=0, le=1)
    esi_wage_ceiling: Decimal = Field(Decimal("21000"), ge=0)
    pt_state: str = "TELANGANA"
    pt_slabs: Optional[list] = None
    default_tax_regime: str = Field("NEW", pattern="^(NEW|OLD)$")
    lop_basis: str = Field("CALENDAR_DAYS", pattern="^(CALENDAR_DAYS|FIXED_30)$")
    effective_from: date = Field(default_factory=date.today)


class InvestmentDeclarationUpsert(BaseModel):
    employee_id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    financial_year: str = Field(..., pattern=r"^\d{4}-\d{4}$", description="e.g. 2026-2027")
    section_80c: Decimal = Field(Decimal("0"), ge=0)
    section_80d: Decimal = Field(Decimal("0"), ge=0)
    section_80ccd1b_nps: Decimal = Field(Decimal("0"), ge=0)
    home_loan_interest_24b: Decimal = Field(Decimal("0"), ge=0)
    other_deductions: Decimal = Field(Decimal("0"), ge=0)
    verified_by_hr: bool = False
