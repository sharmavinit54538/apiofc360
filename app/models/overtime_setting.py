"""SQLAlchemy models for Enterprise Overtime Management System."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PayrollOvertimeSetting(Base):
    """Central Overtime Policy & Calculation Rules entity."""
    __tablename__ = "payroll_overtime_settings"
    __table_args__ = (
        Index("ix_payroll_overtime_settings_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    overtime_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    overtime_code: Mapped[str] = mapped_column(String(50), nullable=False, default="OT_POLICY_STD", server_default=text("'OT_POLICY_STD'"))
    calc_method: Mapped[str] = mapped_column(String(40), nullable=False, default="HOURLY_MULTIPLIER", server_default=text("'HOURLY_MULTIPLIER'"))
    # HOURLY_MULTIPLIER | FIXED_AMOUNT | BASIC_PERCENTAGE | FORMULA

    # Multipliers
    standard_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1.5, server_default=text("1.5"))
    weekend_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1.5, server_default=text("1.5"))
    holiday_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=2.0, server_default=text("2.0"))
    night_shift_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1.25, server_default=text("1.25"))
    emergency_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=2.5, server_default=text("2.5"))

    # Caps & Policy Thresholds
    min_hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=1.0, server_default=text("1.0"))
    max_hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=4.0, server_default=text("4.0"))
    max_hours_per_week: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=16.0, server_default=text("16.0"))
    max_hours_per_month: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=50.0, server_default=text("50.0"))

    # Approvals & Comp-Off
    auto_approval_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    auto_approval_threshold_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=2.0, server_default=text("2.0"))
    require_manager_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    comp_off_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    comp_off_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90, server_default=text("90"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class OvertimeRule(Base):
    """Tiered or department-specific overtime rules."""
    __tablename__ = "overtime_rules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_overtime_settings.id", ondelete="CASCADE"), nullable=False)

    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1.5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class PayrollOvertimeHistory(Base):
    """Immutable version snapshots of overtime policy settings."""
    __tablename__ = "payroll_overtime_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_overtime_settings.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollOvertimeAuditLog(Base):
    """Audit log entries for overtime policy changes."""
    __tablename__ = "payroll_overtime_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_overtime_settings.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
