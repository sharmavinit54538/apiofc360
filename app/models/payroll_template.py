"""SQLAlchemy models for Enterprise Payroll Template Management System."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PayrollTemplate(Base):
    """Central Payroll & Document Template entity."""
    __tablename__ = "payroll_templates"
    __table_args__ = (
        UniqueConstraint("company_id", "template_code", name="uq_payroll_template_code"),
        Index("ix_payroll_templates_company_id", "company_id"),
        Index("ix_payroll_templates_code", "template_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_code: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="PAYSLIP")
    # PAYSLIP | OFFER_LETTER | APPOINTMENT_LETTER | SALARY_REVISION | BONUS_LETTER | TAX_DECLARATION | BANK_ADVICE

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doc_format: Mapped[str] = mapped_column(String(20), nullable=False, default="PDF") # PDF | HTML | DOCX
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="EN")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PUBLISHED", server_default=text("'PUBLISHED'"))
    # DRAFT | PUBLISHED | ARCHIVED

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    styling_theme: Mapped[str] = mapped_column(String(50), nullable=False, default="MODERN_DARK")
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    header_logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    footer_text: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TemplateVersion(Base):
    """Immutable version snapshots for templates."""
    __tablename__ = "payroll_template_versions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_templates.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollTemplateHistory(Base):
    """Template change history logs."""
    __tablename__ = "payroll_template_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_templates.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollTemplateAuditLog(Base):
    """Audit log entries for template operations."""
    __tablename__ = "payroll_template_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_templates.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
