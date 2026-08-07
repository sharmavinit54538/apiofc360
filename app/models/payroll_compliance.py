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

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(50), nullable=False) # e.g. "July 2026"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING") # PENDING | FILED | OVERDUE
    challan_number: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ComplianceChallan(Base):
    """Generated statutory challans and ECR records."""
    __tablename__ = "payroll_compliance_challans"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    compliance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_compliance.id", ondelete="SET NULL"), nullable=True)

    challan_type: Mapped[str] = mapped_column(String(50), nullable=False) # EPFO_ECR | ESIC_CHALLAN | PT_CHALLAN | TDS_CHALLAN
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    trrn_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="GENERATED") # GENERATED | PAID | FILED
    file_payload: Mapped[str | None] = mapped_column(String, nullable=True) # Text payload for ECR

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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


class ComplianceAuditLog(Base):
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
