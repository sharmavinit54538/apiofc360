"""SQLAlchemy models for Enterprise Tax Management System."""
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


class PayrollTaxSetting(Base):
    """Central Tax Rule & Compliance entity."""
    __tablename__ = "payroll_tax_settings"
    __table_args__ = (
        UniqueConstraint("company_id", "tax_code", name="uq_payroll_tax_company_code"),
        Index("ix_payroll_tax_settings_company_id", "company_id"),
        Index("ix_payroll_tax_settings_tax_code", "tax_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    tax_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_code: Mapped[str] = mapped_column(String(50), nullable=False)
    tax_type: Mapped[str] = mapped_column(String(40), nullable=False, default="INCOME_TAX_NEW")
    # INCOME_TAX_OLD | INCOME_TAX_NEW | TDS | PROFESSIONAL_TAX | PF_EPF | ESI | LWF | GRATUITY | NPS | CUSTOM_TAX

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False, default="2026-2027", server_default=text("'2026-2027'"))
    country: Mapped[str] = mapped_column(String(10), nullable=False, default="IND", server_default=text("'IND'"))
    state: Mapped[str | None] = mapped_column(String(50), nullable=True, default="TELANGANA")

    calc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="PROGRESSIVE_SLAB")
    # FIXED | PERCENTAGE | PROGRESSIVE_SLAB | FORMULA

    employee_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True, default=0)
    employer_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True, default=0)
    wage_ceiling: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0)
    std_deduction: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=75000)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    slabs: Mapped[List[PayrollTaxSlab]] = relationship("PayrollTaxSlab", back_populates="tax_setting", cascade="all, delete-orphan")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PayrollTaxSlab(Base):
    """Progressive tax slab tiers for income tax or PT."""
    __tablename__ = "payroll_tax_slabs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tax_setting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_tax_settings.id", ondelete="CASCADE"), nullable=False)

    min_income: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    max_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True) # None = No upper ceiling
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0) # 0.05 for 5%
    flat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    tax_setting: Mapped[PayrollTaxSetting] = relationship("PayrollTaxSetting", back_populates="slabs")


class PayrollTaxHistory(Base):
    """Immutable version snapshots of tax configurations."""
    __tablename__ = "payroll_tax_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tax_setting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_tax_settings.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollTaxAuditLog(Base):
    """Audit log entries for statutory tax changes."""
    __tablename__ = "payroll_tax_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tax_setting_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_tax_settings.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
