"""DPDP Act consent, retention and data-subject request ledger models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin


class ConsentPurposeCode(str, enum.Enum):
    PAYROLL_PROCESSING = "PAYROLL_PROCESSING"
    BGV_VERIFICATION = "BGV_VERIFICATION"
    BIOMETRIC_ATTENDANCE = "BIOMETRIC_ATTENDANCE"
    TAX_FILING = "TAX_FILING"


class ConsentStatus(str, enum.Enum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class DataSubjectRequestType(str, enum.Enum):
    EXPORT = "EXPORT"
    ERASURE = "ERASURE"
    CORRECTION = "CORRECTION"


class DataSubjectRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED_STATUTORY_HOLD = "REJECTED_STATUTORY_HOLD"


# Short aliases for callers that use the names from the compliance design.
PurposeCode = ConsentPurposeCode
RequestType = DataSubjectRequestType
RequestStatus = DataSubjectRequestStatus


class DataConsentLedger(TenantMixin, TimestampMixin, Base):
    """Append-only record of each consent grant or withdrawal."""

    __tablename__ = "data_consent_ledger"
    __table_args__ = (
        Index("ix_data_consent_ledger_company_employee", "company_id", "employee_id"),
        Index("ix_data_consent_ledger_employee_purpose", "employee_id", "purpose_code"),
        Index("ix_data_consent_ledger_company_status", "company_id", "consent_status"),
        CheckConstraint(
            "purpose_code IN ('PAYROLL_PROCESSING', 'BGV_VERIFICATION', 'BIOMETRIC_ATTENDANCE', 'TAX_FILING')",
            name="purpose_code_allowed",
        ),
        CheckConstraint(
            "consent_status IN ('GRANTED', 'WITHDRAWN')",
            name="consent_status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    purpose_code: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConsentStatus.GRANTED.value, server_default=text("'GRANTED'")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataRetentionPolicy(TenantMixin, TimestampMixin, Base):
    """Tenant-specific legal retention windows for personal-data entities."""

    __tablename__ = "data_retention_policies"
    __table_args__ = (
        UniqueConstraint("company_id", "entity_type", name="uq_data_retention_policy_company_entity"),
        Index("ix_data_retention_policies_company_id", "company_id"),
        CheckConstraint("retention_days >= 0", name="retention_days_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Eight years for statutory Indian payroll/tax records.
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2920, server_default=text("2920")
    )
    auto_anonymise_after_exit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class DataSubjectRequest(TenantMixin, TimestampMixin, Base):
    """Auditable lifecycle for export, erasure and correction requests."""

    __tablename__ = "data_subject_requests"
    __table_args__ = (
        Index("ix_data_subject_requests_company_employee", "company_id", "employee_id"),
        Index("ix_data_subject_requests_company_status", "company_id", "status"),
        CheckConstraint(
            "request_type IN ('EXPORT', 'ERASURE', 'CORRECTION')",
            name="request_type_allowed",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'EXECUTED', 'REJECTED_STATUTORY_HOLD')",
            name="request_status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default=DataSubjectRequestStatus.PENDING.value, server_default=text("'PENDING'")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    execution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "ConsentPurposeCode",
    "ConsentStatus",
    "DataConsentLedger",
    "DataRetentionPolicy",
    "DataSubjectRequest",
    "DataSubjectRequestStatus",
    "DataSubjectRequestType",
    "PurposeCode",
    "RequestStatus",
    "RequestType",
]
