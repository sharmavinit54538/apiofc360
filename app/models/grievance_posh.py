"""Confidential employee grievance and POSH (ICC) persistence.

Reporter identity is never included in anonymous service representations.  POSH
 evidence is stored as authenticated ciphertext, not as an uploaded plain file.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin


class GrievanceCase(TenantMixin, TimestampMixin, Base):
    __tablename__ = "grievance_cases"
    __table_args__ = (
        UniqueConstraint("company_id", "case_number", name="uq_grievance_company_number"),
        Index("ix_grievance_cases_company_status", "company_id", "status"),
        Index("ix_grievance_cases_sla", "sla_due_at", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(40), nullable=False)
    reporter_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    receipt_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    accused_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL", server_default=text("'NORMAL'"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN", server_default=text("'OPEN'"))
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    investigator_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    appeal_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["GrievanceCaseEvent"]] = relationship(
        "GrievanceCaseEvent", back_populates="case", cascade="all, delete-orphan", lazy="select"
    )


class GrievanceCaseEvent(TimestampMixin, Base):
    """Restricted audit trail; event metadata must not contain anonymous identity."""

    __tablename__ = "grievance_case_events"
    __table_args__ = (Index("ix_grievance_events_case", "case_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("grievance_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    case: Mapped[GrievanceCase] = relationship("GrievanceCase", back_populates="events", lazy="select")


class ICCCommittee(TenantMixin, TimestampMixin, Base):
    __tablename__ = "posh_icc_committees"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_posh_icc_company_name"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    term_start: Mapped[date] = mapped_column(Date, nullable=False)
    term_end: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    members: Mapped[list["ICCMember"]] = relationship(
        "ICCMember", back_populates="committee", cascade="all, delete-orphan", lazy="select"
    )


class ICCMember(TimestampMixin, Base):
    __tablename__ = "posh_icc_members"
    __table_args__ = (Index("ix_posh_icc_members_committee", "committee_id", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    committee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posh_icc_committees.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    appointed_at: Mapped[date] = mapped_column(Date, nullable=False)

    committee: Mapped[ICCCommittee] = relationship("ICCCommittee", back_populates="members", lazy="select")


class POSHComplaint(TenantMixin, TimestampMixin, Base):
    __tablename__ = "posh_complaints"
    __table_args__ = (
        UniqueConstraint("company_id", "complaint_number", name="uq_posh_company_complaint_number"),
        Index("ix_posh_complaints_inquiry_due", "inquiry_due_at", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_number: Mapped[str] = mapped_column(String(40), nullable=False)
    committee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posh_icc_committees.id", ondelete="RESTRICT"), nullable=False
    )
    reporter_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    receipt_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    accused_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="FILED", server_default=text("'FILED'"))
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inquiry_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conciliation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    conciliation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    conciliation_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    conciliated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inquiry_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inquiry_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recommendation_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    evidence: Mapped[list["POSHEvidence"]] = relationship(
        "POSHEvidence", back_populates="complaint", cascade="all, delete-orphan", lazy="select"
    )


class POSHEvidence(TimestampMixin, Base):
    """Encrypted evidence vault entry.  Plaintext and encryption keys are not stored."""

    __tablename__ = "posh_evidence_vault"
    __table_args__ = (Index("ix_posh_evidence_complaint", "complaint_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posh_complaints.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1", server_default=text("'v1'"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    complaint: Mapped[POSHComplaint] = relationship("POSHComplaint", back_populates="evidence", lazy="select")


class POSHTrainingRecord(TenantMixin, TimestampMixin, Base):
    __tablename__ = "posh_training_records"
    __table_args__ = (Index("ix_posh_training_company_employee", "company_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True
    )
    icc_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posh_icc_members.id", ondelete="CASCADE"), nullable=True
    )
    audience: Mapped[str] = mapped_column(String(20), nullable=False)  # EMPLOYEE | ICC
    training_title: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(150), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    certificate_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)


class POSHAnnualReturn(TenantMixin, TimestampMixin, Base):
    """Immutable generated Section 21 / Section 22 annual-return snapshot."""

    __tablename__ = "posh_annual_returns"
    __table_args__ = (UniqueConstraint("company_id", "return_year", name="uq_posh_annual_return_year"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    return_year: Mapped[int] = mapped_column(Integer, nullable=False)
    section_21: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    section_22: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
