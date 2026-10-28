"""SQLAlchemy models for Enterprise Payroll Compliance Management System."""
from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, Date, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, func, text, BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.db.base import Base


class PayrollCompliance(Base):
    """Central Statutory Payroll Compliance Rule entity."""
    __tablename__ = "payroll_compliance"
    __table_args__ = (
        UniqueConstraint("company_id", "compliance_code", name="uq_payroll_compliance_code"),
        Index("ix_payroll_compliance_company_id", "company_id"),
        Index("ix_payroll_compliance_code", "compliance_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    compliance_name: Mapped[str] = mapped_column(String(100), nullable=False)
    compliance_code: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="EPF")
    # EPF | ESI | PT | LWF | TDS | GRATUITY | BONUS | MINIMUM_WAGES | MATERNITY_BENEFIT | CONTRACT_LABOUR

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False, default="2026-2027", server_default=text("'2026-2027'"))
    state: Mapped[str | None] = mapped_column(String(50), nullable=True, default="ALL_INDIA")

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COMPLIANT", server_default=text("'COMPLIANT'"))
    # COMPLIANT | WARNING | DUE_SOON | OVERDUE

    filing_frequency: Mapped[str] = mapped_column(String(30), nullable=False, default="MONTHLY") # MONTHLY | QUARTERLY | SEMI_ANNUAL | ANNUAL
    due_day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=15)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    auto_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    auto_remind: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    compliance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default=text("100"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StateStatutoryRule(Base):
    """Versioned state-level PT and LWF rules.

    Amounts are stored in paise so a rule can be evaluated without binary
    floating-point rounding.  ``company_id`` is nullable for the seeded
    all-tenant defaults; a tenant-specific row takes precedence over the
    default for the same state and effective date.
    """

    __tablename__ = "state_statutory_rules"
    __table_args__ = (
        Index("ix_state_statutory_rules_state_effective", "state_code", "effective_from"),
        Index("ix_state_statutory_rules_company_state", "company_id", "state_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    state_name: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, default=date(2020, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    pt_slabs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lwf_employee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    lwf_employer_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    lwf_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY", server_default=text("'MONTHLY'"))
    lwf_applicable_months: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    needs_ca_validation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Integration-friendly aliases; all resolve to the same persisted columns.
    state = synonym("state_code")
    pt_slabs = synonym("pt_slabs_json")
    lwf_applicable_months_json = synonym("lwf_applicable_months")
    lwf_employee_contribution_paise = synonym("lwf_employee_paise")
    lwf_employer_contribution_paise = synonym("lwf_employer_paise")
    ca_validation_required = synonym("needs_ca_validation")


class FinancialYearTaxRule(Base):
    """Configurable old/new-regime tax slabs and deduction limits for one FY."""

    __tablename__ = "financial_year_tax_rules"
    __table_args__ = (
        UniqueConstraint("company_id", "financial_year", "regime", name="uq_fy_tax_rule_company_year_regime"),
        Index("ix_fy_tax_rules_year_regime", "financial_year", "regime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    regime: Mapped[str] = mapped_column(String(10), nullable=False)
    slabs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    standard_deduction_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    rebate_87a_limit_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    rebate_87a_max_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    chapter_via_limits_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    surcharge_slabs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False, default=Decimal("0.04"), server_default=text("0.04"))
    proof_cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    needs_ca_validation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ComplianceDueDate(Base):
    """Statutory filing due dates calendar."""
    __tablename__ = "payroll_compliance_due_dates"
    __table_args__ = (
        Index("ix_payroll_compliance_due_dates_company", "company_id", "period_year", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    challan_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance_challans.id", ondelete="SET NULL"), nullable=True)
    period_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(50), nullable=False) # e.g. "July 2026"
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING") 
    # PENDING | ECR_GENERATED | CHALLAN_UPLOADED | FILED_ON_TIME | OVERDUE

    challan_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trrn_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    utr_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    overdue_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    interest_7q_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default=text("0"))
    damages_14b_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default=text("0"))
    filing_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY", server_default=text("'MONTHLY'"))
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filing_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ComplianceChallan(Base):
    """Generated statutory challans, TRRN records, and ECR returns."""
    __tablename__ = "payroll_compliance_challans"
    __table_args__ = (
        Index("ix_payroll_compliance_challans_company", "company_id", "period_year", "period_month"),
        Index("ix_payroll_compliance_challans_trrn", "trrn_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    period_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True)

    challan_type: Mapped[str] = mapped_column(String(50), nullable=False, default="EPFO_ECR") # EPFO_ECR | ESIC_CHALLAN | PT_CHALLAN | TDS_CHALLAN
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    trrn_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    crn_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bsr_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    challan_serial_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    challan_generation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    utr_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    challan_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    challan_file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_receipt_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    epf_employee_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    epf_employer_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    eps_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    edli_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    admin_charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="GENERATED") 
    # GENERATED | ECR_GENERATED | CHALLAN_UPLOADED | FILED_ON_TIME | OVERDUE | PAID
    file_payload: Mapped[str | None] = mapped_column(String, nullable=True) # Text payload for ECR (#|~|# delimited)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StatutoryForm(Base):
    """Generated Form 138 / Form 130 drafts and their immutable source data."""

    __tablename__ = "statutory_forms"
    __table_args__ = (
        Index("ix_statutory_forms_company_type_period", "company_id", "form_type", "period_id"),
        Index("ix_statutory_forms_employee_year", "employee_id", "financial_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True
    )
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)  # FORM_138 | FORM_130
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_errors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ComplianceHistory(Base):
    """Immutable version snapshots of compliance settings."""
    __tablename__ = "payroll_compliance_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollComplianceAuditLog(Base):
    """Audit log entries for statutory compliance changes."""
    __tablename__ = "payroll_compliance_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# Backwards compatibility alias
ComplianceAuditLog = PayrollComplianceAuditLog

