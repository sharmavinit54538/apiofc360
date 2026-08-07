"""SQLAlchemy models for Salary Components & Calculation Engine."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SalaryComponent(Base):
    """Central Salary Component Definition entity."""
    __tablename__ = "salary_components"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_salary_component_company_code"),
        Index("ix_salary_components_company_id", "company_id"),
        Index("ix_salary_components_code", "code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    component_type: Mapped[str] = mapped_column(String(30), nullable=False, default="EARNING")
    # EARNING | DEDUCTION | REIMBURSEMENT | EMPLOYER_CONTRIB | EMPLOYEE_CONTRIB | TAX | VARIABLE | ONE_TIME

    category: Mapped[str] = mapped_column(String(50), nullable=False, default="BASIC")
    # BASIC | HRA | DA | SPECIAL | CONVEYANCE | MEDICAL | LTA | BONUS | INCENTIVE | COMMISSION | OVERTIME | GRATUITY | PF | ESI | PT | TDS | LWF | OTHER

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payroll_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    # Calculation Rules
    calc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FIXED")
    # FIXED | PERCENTAGE_BASIC | PERCENTAGE_GROSS | PERCENTAGE_CTC | FORMULA | ATTENDANCE_BASED | WORKING_DAYS | OVERTIME_BASED | PERFORMANCE_BASED | MANUAL

    formula_expr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)
    percentage_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True, default=0)

    # Compliance & Accounting Flags
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    pf_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    esi_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    pt_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    included_in_ctc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    included_in_gross: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    included_in_net: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    appears_on_payslip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    employee_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    hr_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SalaryComponentHistory(Base):
    """Immutable version snapshots of salary component definitions."""
    __tablename__ = "salary_component_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("salary_components.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalaryComponentAuditLog(Base):
    """Audit log entries for salary component mutations."""
    __tablename__ = "salary_component_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("salary_components.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
