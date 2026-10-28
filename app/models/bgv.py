"""Background verification consent, vendor, checks, and discrepancy models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.field_encryption import EncryptedString
from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin

if TYPE_CHECKING:
    from app.models.recruitment import Application, Candidate


class BGVVendor(EnterpriseModelMixin, Base):
    __tablename__ = "bgv_vendors"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_bgv_vendor_company_name"),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    cases: Mapped[list[BGVCase]] = relationship("BGVCase", back_populates="vendor", lazy="select")


class BGVCase(EnterpriseModelMixin, Base):
    __tablename__ = "bgv_cases"
    __table_args__ = (
        Index("ix_bgv_cases_company_status", "company_id", "status"),
        Index("ix_bgv_cases_application", "application_id"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("bgv_vendors.id", ondelete="RESTRICT"), nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING_CONSENT", server_default=text("'PENDING_CONSENT'"))
    vendor_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    consent_user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    consent_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vendor: Mapped[BGVVendor] = relationship("BGVVendor", back_populates="cases", lazy="select")
    checks: Mapped[list[BGVCheck]] = relationship(
        "BGVCheck", back_populates="case", cascade="all, delete-orphan", lazy="select",
    )


class BGVCheck(EnterpriseModelMixin, Base):
    __tablename__ = "bgv_checks"
    __table_args__ = (
        UniqueConstraint("case_id", "check_type", name="uq_bgv_check_case_type"),
        Index("ix_bgv_checks_company_status", "company_id", "status"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("bgv_cases.id", ondelete="CASCADE"), nullable=False)
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    vendor_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    discrepancy_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    discrepancy_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped[BGVCase] = relationship("BGVCase", back_populates="checks", lazy="select")


class BGVWebhookEvent(EnterpriseModelMixin, Base):
    __tablename__ = "bgv_webhook_events"
    __table_args__ = (UniqueConstraint("company_id", "vendor_id", "external_event_id", name="uq_bgv_webhook_event"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("bgv_vendors.id", ondelete="CASCADE"), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(150), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
