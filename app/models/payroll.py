"""Payroll domain models — complete module.

Covers: statutory config, salary structures, attendance input, payroll runs,
payslips, tax investment declarations, pay-cycle FSM, audit log, overtime,
bonuses/incentives, deductions, advances/loans, reimbursements, bank
transfers, compliance obligations, and AI insights snapshots.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class StatutoryComplianceConfig(Base):
    """Per-company, versioned statutory rates. NEVER hardcode PF/ESI/PT/TDS numbers
    in service code — always read from the active row here, so HR/finance can update
    rates the moment government notifications change, with zero redeploy."""

    __tablename__ = "statutory_compliance_configs"
    __table_args__ = (Index("ix_statutory_configs_company_id", "company_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    # General Settings
    company_name: Mapped[str] = mapped_column(String(100), nullable=False, default="Aurix AI Enterprise", server_default=text("'Aurix AI Enterprise'"))
    legal_business_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tan_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cin_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR", server_default=text("'INR'"))
    country: Mapped[str] = mapped_column(String(50), nullable=False, default="India", server_default=text("'India'"))
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Asia/Kolkata", server_default=text("'Asia/Kolkata'"))
    financial_year_start: Mapped[str] = mapped_column(String(10), nullable=False, default="04-01", server_default=text("'04-01'"))
    payroll_start_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    payroll_end_day: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default=text("30"))
    salary_payment_date: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    working_days_policy: Mapped[str | None] = mapped_column(String(50), nullable=True, default="EXCLUDE_WEEKENDS")
    salary_calc_method: Mapped[str | None] = mapped_column(String(50), nullable=True, default="MONTHLY_FIXED")
    attendance_source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="FACE_BIOMETRIC")
    payslip_footer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    digital_signature_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_levels: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default=text("2"))
    auto_lock_payroll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    enable_draft_payroll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    enable_retro_payroll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    # Pay Cycle
    pay_cycle_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY", server_default=text("'MONTHLY'"))
    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    cutoff_date: Mapped[int] = mapped_column(Integer, nullable=False, default=25, server_default=text("25"))
    preview_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default=text("5"))

    # Statutory & Tax
    pf_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    employee_pf_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.12"))
    employer_pf_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.12"))
    pf_wage_ceiling: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("15000.00"))
    pf_on_full_basic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    esi_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    employee_esi_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0075"))
    employer_esi_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0325"))
    esi_wage_ceiling: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("21000.00"))

    pt_state: Mapped[str] = mapped_column(String(50), nullable=False, default="TELANGANA", server_default=text("'TELANGANA'"))
    pt_slabs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    default_tax_regime: Mapped[str] = mapped_column(String(10), nullable=False, default="NEW", server_default=text("'NEW'"))
    lop_basis: Mapped[str] = mapped_column(String(20), nullable=False, default="CALENDAR_DAYS", server_default=text("'CALENDAR_DAYS'"))

    # Overtime & Bonuses
    overtime_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    overtime_multiplier_holiday: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("2.0"))
    overtime_multiplier_weekend: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1.5"))
    overtime_multiplier_night: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1.25"))

    # Banking & Automation
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False, default="HDFC Bank", server_default=text("'HDFC Bank'"))
    bank_ifsc: Mapped[str] = mapped_column(String(20), nullable=False, default="HDFC0001234", server_default=text("'HDFC0001234'"))
    salary_transfer_format: Mapped[str] = mapped_column(String(20), nullable=False, default="NEFT", server_default=text("'NEFT'"))
    auto_email_payslips: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    auto_backup_payroll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    settings_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PayrollSettingsHistory(Base):
    """Immutable version history of payroll configuration snapshots."""
    __tablename__ = "payroll_settings_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalaryStructure(Base):
    """Versioned CTC breakup for one employee. Creating a new structure closes the
    previous active row's effective_to (service-layer responsibility, not a DB trigger)."""

    __tablename__ = "salary_structures"
    __table_args__ = (
        Index("ix_salary_structures_employee_id", "employee_id"),
        Index("ix_salary_structures_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    annual_ctc: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    basic_monthly: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    hra_monthly: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    conveyance_monthly: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    special_allowance_monthly: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    other_allowances: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"Meal Allowance": 1500}
    annual_bonus: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    is_metro_city: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    rent_paid_monthly: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)  # HRA exemption input (old regime)
    tax_regime: Mapped[str] = mapped_column(String(10), nullable=False, default="NEW", server_default=text("'NEW'"))

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class PayrollAttendanceInput(Base):
    """HR-entered (or future attendance-module-fed) LOP days per employee per period.
    Absence of a row for an employee/period == 0 LOP (full pay)."""

    __tablename__ = "payroll_attendance_inputs"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_month", "period_year", name="uq_attendance_employee_period"),
        Index("ix_attendance_inputs_company_period", "company_id", "period_year", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    lop_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    arrears: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    one_time_bonus: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    remarks: Mapped[str | None] = mapped_column(String(255), nullable=True)

    entered_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PayrollRun(Base):
    """One payroll cycle for one company for one calendar month."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "period_month", "period_year", name="uq_payroll_run_company_period"),
        Index("ix_payroll_runs_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))  # DRAFT/PROCESSING/PROCESSED/APPROVED/PAID/VOID/FAILED

    total_employees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_gross: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    total_net: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)

    run_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    payslips: Mapped[list[Payslip]] = relationship("Payslip", back_populates="payroll_run", cascade="all, delete-orphan", lazy="select")


class Payslip(Base):
    """One employee's computed payslip for one payroll run. This is the real,
    period-specific output the old flat Employee columns could never represent."""

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_month", "period_year", name="uq_payslip_employee_period"),
        Index("ix_payslips_company_id", "company_id"),
        Index("ix_payslips_employee_id", "employee_id"),
        Index("ix_payslips_payroll_run_id", "payroll_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    salary_structure_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("salary_structures.id", ondelete="SET NULL"), nullable=True)

    payslip_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)  # e.g. PAY-202607-00042
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)

    total_days_in_month: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    lop_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)

    basic: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    hra: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    conveyance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    special_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    other_allowances_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    arrears: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    bonus: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    lop_deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    gross_earnings: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    employee_pf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    employer_pf: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # informational, part of CTC not net deduction
    employee_esi: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    employer_esi: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # informational
    professional_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    tds: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    net_pay: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    net_pay_words: Mapped[str | None] = mapped_column(String(500), nullable=True)

    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING/PAID/HOLD/FAILED
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_SENT", server_default=text("'NOT_SENT'"))  # NOT_SENT/SENT/DELIVERED/OPENED/FAILED
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    payroll_run: Mapped[PayrollRun] = relationship("PayrollRun", back_populates="payslips", lazy="select")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class EmployeeInvestmentDeclaration(Base):
    """Employee's tax-saving declaration for one financial year — feeds the old-regime
    TDS estimate. Best-effort payroll estimate, not a substitute for CA-level filing."""

    __tablename__ = "employee_investment_declarations"
    __table_args__ = (
        UniqueConstraint("employee_id", "financial_year", name="uq_declaration_employee_fy"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)  # "2026-2027"
    tax_regime: Mapped[str] = mapped_column(String(10), nullable=False, default="OLD", server_default=text("'OLD'"))  # OLD|NEW
    section_80c: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)   # capped 1,50,000 in calc
    section_80d: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    section_80ccd1b_nps: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # capped 50,000
    home_loan_interest_24b: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # capped 2,00,000
    section_80g: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    hra_claimed: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    lta_claimed: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|APPROVED|REJECTED
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_by_hr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    verified_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# =============================================================================
# NEW MODELS — Complete Payroll Module
# =============================================================================

class PayCycle(Base):
    """Central pay-cycle entity. Status FSM:
    DRAFT → SCHEDULED → RUNNING → LOCKED → PROCESSING → COMPLETED → CANCELLED → ARCHIVED
    """
    __tablename__ = "pay_cycles"
    __table_args__ = (
        Index("ix_pay_cycles_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Monthly Payroll Cycle")
    frequency: Mapped[str] = mapped_column(String(30), nullable=False, default="MONTHLY")
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )  # DRAFT | SCHEDULED | RUNNING | LOCKED | PROCESSING | COMPLETED | CANCELLED | ARCHIVED

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    processing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payslip_generation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    attendance_lock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    leave_lock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    overtime_lock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_calculation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bonus_processing_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    locks: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    automation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Aggregated totals (populated during SALARY_PROCESSING)
    total_employees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_reimbursements: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_bonuses: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    # Lifecycle actors
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disbursed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    validation_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    audit_logs: Mapped[list["PayrollAuditLog"]] = relationship("PayrollAuditLog", back_populates="pay_cycle", cascade="all, delete-orphan", lazy="select")


class PayrollCycleHistory(Base):
    """Immutable version history of payroll cycle state changes."""
    __tablename__ = "payroll_cycle_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollCycleLog(Base):
    """Granular action logs for payroll cycle lifecycle events."""
    __tablename__ = "payroll_cycle_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="CASCADE"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollAuditLog(Base):
    """Immutable append-only log of every state-changing payroll action."""
    __tablename__ = "payroll_audit_logs"
    __table_args__ = (Index("ix_payroll_audit_logs_pay_cycle_id", "pay_cycle_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="CASCADE"), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)   # PayCycle|Payslip|BonusAward|...
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)         # CREATED|LOCKED|APPROVED|REJECTED|REOPENED|...
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    pay_cycle: Mapped["PayCycle | None"] = relationship("PayCycle", back_populates="audit_logs", lazy="select")


class OvertimePolicy(Base):
    """Configurable OT rate per role/grade/company."""
    __tablename__ = "overtime_policies"
    __table_args__ = (Index("ix_overtime_policies_company_id", "company_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    applicable_role: Mapped[str | None] = mapped_column(String(100), nullable=True)   # null = applies to all
    applicable_grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rate_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1.5"))  # e.g. 1.5x
    max_ot_hours_per_month: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class OvertimeEntry(Base):
    """Computed OT hours per employee per period — reviewable before pushing into PayCycle."""
    __tablename__ = "overtime_entries"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_month", "period_year", name="uq_ot_employee_period"),
        Index("ix_overtime_entries_company_period", "company_id", "period_year", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    adjusted_hours: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)  # HR override
    ot_rate_per_hour: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    ot_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|APPROVED|PUSHED
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BonusPlan(Base):
    """Spot award or recurring incentive plan with eligibility criteria."""
    __tablename__ = "bonus_plans"
    __table_args__ = (Index("ix_bonus_plans_company_id", "company_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="SPOT")  # SPOT|RECURRING
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    eligibility_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")  # ALL|EMPLOYEE|DEPARTMENT|ROLE|GRADE
    eligible_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # list of UUIDs or names
    default_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    recurrence_months: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = one-time
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BonusAward(Base):
    """Actual bonus award to one employee — goes through approval before queuing into PayCycle."""
    __tablename__ = "bonus_awards"
    __table_args__ = (Index("ix_bonus_awards_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    bonus_plan_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("bonus_plans.id", ondelete="SET NULL"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|APPROVED|REJECTED|QUEUED|PAID
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DeductionComponent(Base):
    """Statutory (PF/ESI/PT auto-computed) and voluntary/one-off deductions per employee per cycle."""
    __tablename__ = "deduction_components"
    __table_args__ = (
        Index("ix_deduction_components_employee_id", "employee_id"),
        Index("ix_deduction_components_pay_cycle_id", "pay_cycle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    deduction_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PF|ESI|PT|LWF|TDS|LOAN_EMI|ADVANCE|VOLUNTARY|ONE_OFF
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)  # FK to loan/advance if applicable
    remarks: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AdvanceLoan(Base):
    """Advance or loan issued to an employee with EMI tracking."""
    __tablename__ = "advance_loans"
    __table_args__ = (Index("ix_advance_loans_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    loan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ADVANCE")  # ADVANCE|LOAN
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    outstanding_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    emi_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installments_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_from_month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12
    start_from_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))  # ACTIVE|CLOSED|CANCELLED
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    installments: Mapped[list["AdvanceLoanInstallment"]] = relationship("AdvanceLoanInstallment", back_populates="loan", cascade="all, delete-orphan", lazy="select")


class AdvanceLoanInstallment(Base):
    """Per-cycle EMI deduction record — auto-generated by the salary processing engine."""
    __tablename__ = "advance_loan_installments"
    __table_args__ = (
        UniqueConstraint("loan_id", "period_month", "period_year", name="uq_loan_installment_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("advance_loans.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    emi_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|DEDUCTED|FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    loan: Mapped["AdvanceLoan"] = relationship("AdvanceLoan", back_populates="installments", lazy="select")


class ReimbursementClaim(Base):
    """Employee expense claim with approval workflow."""
    __tablename__ = "reimbursement_claims"
    __table_args__ = (
        Index("ix_reimbursement_claims_employee_id", "employee_id"),
        Index("ix_reimbursement_claims_pay_cycle_id", "pay_cycle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # TRAVEL|MEDICAL|FOOD|EQUIPMENT|OTHER
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUBMITTED", server_default=text("'SUBMITTED'"))  # SUBMITTED|APPROVED|REJECTED|QUEUED|PAID
    payout_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="CYCLE")  # CYCLE|STANDALONE
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class BankAdviceFile(Base):
    """Generated NEFT/ACH bank advice file metadata per PayCycle."""
    __tablename__ = "bank_advice_files"
    __table_args__ = (Index("ix_bank_advice_files_pay_cycle_id", "pay_cycle_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    pay_cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False, default="NEFT")  # NEFT|ACH|CSV
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="GENERATED", server_default=text("'GENERATED'"))  # GENERATED|SUBMITTED|CONFIRMED
    generated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    file_content: Mapped[str | None] = mapped_column(String, nullable=True)  # CSV/NEFT content stored inline for download

    disbursements: Mapped[list["BankDisbursementRecord"]] = relationship("BankDisbursementRecord", back_populates="advice_file", cascade="all, delete-orphan", lazy="select")


class BankDisbursementRecord(Base):
    """Per-employee disbursement tracking within a BankAdviceFile."""
    __tablename__ = "bank_disbursement_records"
    __table_args__ = (
        UniqueConstraint("advice_file_id", "employee_id", name="uq_disbursement_file_employee"),
        Index("ix_bank_disbursement_records_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    advice_file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("bank_advice_files.id", ondelete="CASCADE"), nullable=False)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(String(15), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|SUCCESS|FAILED
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    advice_file: Mapped["BankAdviceFile"] = relationship("BankAdviceFile", back_populates="disbursements", lazy="select")


class ComplianceObligation(Base):
    """Statutory filing obligation tracker: PF/ESI/PT/LWF/Gratuity."""
    __tablename__ = "compliance_obligations"
    __table_args__ = (Index("ix_compliance_obligations_company_id", "company_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    pay_cycle_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_cycles.id", ondelete="SET NULL"), nullable=True)
    obligation_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PF|ESI|PT|LWF|GRATUITY|TDS
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)     # e.g. "Jul-2026"
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING|FILED|OVERDUE|WAIVED
    challan_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledgement_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    penalty_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    violation_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    documents: Mapped[list["ComplianceDocument"]] = relationship("ComplianceDocument", back_populates="obligation", cascade="all, delete-orphan", lazy="select")


class ComplianceDocument(Base):
    """Filing proof document per compliance obligation."""
    __tablename__ = "compliance_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    obligation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("compliance_obligations.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_url: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    obligation: Mapped["ComplianceObligation"] = relationship("ComplianceObligation", back_populates="documents", lazy="select")


class TaxDeclarationProof(Base):
    """Proof document per investment section per financial year per employee."""
    __tablename__ = "tax_declaration_proofs"
    __table_args__ = (Index("ix_tax_decl_proofs_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    declaration_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_investment_declarations.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    section: Mapped[str] = mapped_column(String(30), nullable=False)  # 80C|80D|80CCD1B|24B|OTHER
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_url: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_claimed: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    verified_by_hr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
