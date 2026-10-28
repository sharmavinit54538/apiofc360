"""Employee onboarding steps and cross-functional provisioning checklist."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee


class EmployeeOnboarding(Base):
    """Onboarding checklist steps tracking for each employee."""

    __tablename__ = "employee_onboarding"
    __table_args__ = (
        Index("ix_employee_onboarding_employee_id", "employee_id"),
        Index("ix_employee_onboarding_offer_id", "offer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Offer-to-preboarding automation metadata is repeated on step rows so the
    # existing ten-step schema remains the canonical onboarding workflow.
    offer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("offers.id", ondelete="SET NULL"), nullable=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    invite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bgv_status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_STARTED", server_default=text("'NOT_STARTED'"))
    bgv_provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    document_validation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completion_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="onboarding_steps")


class OnboardingTaskChecklist(TenantMixin, TimestampMixin, Base):
    """IT, Admin and HR tasks required before an employee joins."""

    __tablename__ = "onboarding_task_checklists"
    __table_args__ = (
        UniqueConstraint("employee_id", "task_key", name="uq_onboarding_task_employee_key"),
        Index("ix_onboarding_tasks_company_status", "company_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # IT | ADMIN | HR
    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped[Employee] = relationship("Employee", lazy="select")


__all__ = ["EmployeeOnboarding", "OnboardingTaskChecklist"]
