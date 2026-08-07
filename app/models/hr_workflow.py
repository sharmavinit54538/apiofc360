"""Database models for AI Workflow Automation Engine.

Includes definitions, active routing instances, and step transitions log.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class HRWorkflowDefinition(Base):
    """Configuration structure defining dynamic event triggers and step rules."""

    __tablename__ = "hr_workflow_definitions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(50), nullable=False)  # LEAVE_REQUESTED, PAYROLL_RUN_COMPLETED, OFFER_CREATED
    rule_criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"department": "Engineering", "ctc_limit": 50000}
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    instances: Mapped[list[HRWorkflowInstance]] = relationship("HRWorkflowInstance", back_populates="definition", cascade="all, delete-orphan", lazy="select")


class HRWorkflowInstance(Base):
    """Running execution tracker of a triggered workflow process."""

    __tablename__ = "hr_workflow_instances"
    __table_args__ = (
        Index("ix_hr_workflow_instances_definition", "workflow_definition_id"),
        Index("ix_hr_workflow_instances_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hr_workflow_definitions.id", ondelete="CASCADE"), nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)  # links to external targets (e.g. leave request ID)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING, RUNNING, COMPLETED, FAILED
    current_step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    definition: Mapped[HRWorkflowDefinition] = relationship("HRWorkflowDefinition", back_populates="instances")
    steps: Mapped[list[HRWorkflowStepInstance]] = relationship("HRWorkflowStepInstance", back_populates="instance", cascade="all, delete-orphan", lazy="select")


class HRWorkflowStepInstance(Base):
    """Modular approval step and recommendation history log."""

    __tablename__ = "hr_workflow_step_instances"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hr_workflow_instances.id", ondelete="CASCADE"), nullable=False)

    step_name: Mapped[str] = mapped_column(String(150), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING, APPROVED, REJECTED, SKIPPED
    decision_recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)  # AUTO_APPROVE, REVIEW_REQUIRED, REJECT
    decision_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    instance: Mapped[HRWorkflowInstance] = relationship("HRWorkflowInstance", back_populates="steps")
    assignee: Mapped[User | None] = relationship("User", lazy="select")
