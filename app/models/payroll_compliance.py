"""SQLAlchemy models for Enterprise Payroll Compliance Management System."""
from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, Date, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

