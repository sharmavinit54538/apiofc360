"""Database models for Settings Management module (Employee, Leave, Document, Asset settings)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, JSON, String,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmployeeSettings(Base):
    """Organization-wide employee management settings."""

    __tablename__ = "employee_settings"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_employee_settings_company_id"),
        Index("ix_employee_settings_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    employee_id_prefix: Mapped[str] = mapped_column(
        String(20), nullable=False, default="EMP", server_default=text("'EMP'")
    )
    employee_id_start_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1001, server_default=text("1001")
    )
    probation_period_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90")
    )
    default_employment_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="full_time", server_default=text("'full_time'")
    )
    default_employee_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default=text("'active'")
    )
    allow_employee_profile_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    require_manager_assignment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LeaveSettings(Base):
    """Organization-wide leave management configuration."""

    __tablename__ = "leave_settings"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_leave_settings_company_id"),
        Index("ix_leave_settings_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    leave_year_start_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    allow_half_day_leave: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    allow_negative_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    require_manager_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    max_consecutive_leave_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    carry_forward_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    carry_forward_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    leave_encashment_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentSettings(Base):
    """Organization-wide employee document management configuration."""

    __tablename__ = "document_settings"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_document_settings_company_id"),
        Index("ix_document_settings_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    allowed_file_types: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=["pdf", "jpg", "jpeg", "png"],
        server_default=text("'[\"pdf\", \"jpg\", \"jpeg\", \"png\"]'"),
    )
    max_file_size_mb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    require_document_verification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    document_expiry_alert_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    employee_can_upload_documents: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    manager_can_view_documents: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssetSettings(Base):
    """Organization-wide asset management configuration."""

    __tablename__ = "asset_settings"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_asset_settings_company_id"),
        Index("ix_asset_settings_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    asset_id_prefix: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AST", server_default=text("'AST'")
    )
    require_assignment_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    enable_asset_return_tracking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    enable_asset_condition_tracking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    enable_warranty_reminders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    warranty_reminder_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    enable_asset_depreciation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
