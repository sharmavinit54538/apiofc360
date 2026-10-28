"""AI Talent Marketplace model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal
from app.db.base import Base
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.employee import Employee

class TalentMatch(Base):
    __tablename__ = "talent_matches"
    __table_args__ = (Index("ix_talent_matches_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    match_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PROJECT, INTERNAL_JOB, MENTOR, TRAINING, CAREER_OPPORTUNITY
    match_title: Mapped[str] = mapped_column(String(200), nullable=False)
    match_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0–100
    ai_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


from app.models.enterprise_common import EnterpriseModelMixin


class InternalJobOpening(EnterpriseModelMixin, Base):
    __tablename__ = "internal_job_openings"
    __table_args__ = (Index("ix_internal_jobs_company_status", "company_id", "status"),)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    min_tenure_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_performance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class InternalJobApplication(EnterpriseModelMixin, Base):
    __tablename__ = "internal_job_applications"
    __table_args__ = (
        UniqueConstraint("opening_id", "employee_id", name="uq_internal_job_application_employee"),
        Index("ix_internal_applications_company_status", "company_id", "status"),
    )

    opening_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("internal_job_openings.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_MANAGER")
    eligibility_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tenure_months_at_application: Mapped[int] = mapped_column(Integer, nullable=False)
    performance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manager_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manager_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
