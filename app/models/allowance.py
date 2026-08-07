"""SQLAlchemy models for Allowance Management System."""
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


class Allowance(Base):
    """Central Allowance Definition entity."""
    __tablename__ = "allowances"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_allowance_company_code"),
        Index("ix_allowances_company_id", "company_id"),
        Index("ix_allowances_code", "code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    category: Mapped[str] = mapped_column(String(50), nullable=False, default="SPECIAL")
    # HRA | DA | CONVEYANCE | MEDICAL | TRAVEL | FOOD | INTERNET | MOBILE | SHIFT | EDUCATION | UNIFORM | VEHICLE | FUEL | REMOTE_WORK | SPECIAL | PROJECT | CITY_COMPENSATORY | PERFORMANCE | SKILL | CUSTOM

    earning_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FIXED")
    is_variable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY") # MONTHLY | QUARTERLY | YEARLY
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    calc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FIXED")
    # FIXED | PERCENTAGE_BASIC | PERCENTAGE_GROSS | PERCENTAGE_CTC | FORMULA | ATTENDANCE_BASED | LOCATION_BASED | GRADE_BASED

    formula_expr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    min_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)
    max_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR", server_default=text("'INR'"))

    # Tax & Exemption Configuration
    taxability_type: Mapped[str] = mapped_column(String(30), nullable=False, default="TAXABLE")
    # TAXABLE | NON_TAXABLE | PARTIALLY_TAXABLE

    exemption_limit_monthly: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)
    exemption_limit_annual: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)

    # Statutory Flags
    pf_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    esi_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    pt_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    lwf_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    included_in_ctc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    included_in_gross: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    included_in_net: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    appears_on_payslip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AllowanceHistory(Base):
    """Immutable version snapshots of allowance definitions."""
    __tablename__ = "allowance_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    allowance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("allowances.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AllowanceAuditLog(Base):
    """Audit log entries for allowance configuration changes."""
    __tablename__ = "allowance_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    allowance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("allowances.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
