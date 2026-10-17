"""SQLAlchemy models for AI Hub Gateway (Agents, Document Generator)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, JSON, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AgentRun(Base):
    """Tracks execution of registered AI Hub agents."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_company_id", "company_id"),
        Index("ix_agent_runs_agent_id", "agent_id"),
        Index("ix_agent_runs_created_at", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, default="manual", server_default=text("'manual'"))
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RUNNING", server_default=text("'RUNNING'"))
    result: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    feedback: Mapped[list[AgentFeedback]] = relationship(
        "AgentFeedback", back_populates="run", cascade="all, delete-orphan"
    )


class AgentFeedback(Base):
    """Feedback and ratings for AI Agent execution runs."""

    __tablename__ = "agent_feedback"
    __table_args__ = (
        Index("ix_agent_feedback_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    run: Mapped[AgentRun] = relationship("AgentRun", back_populates="feedback")


class GeneratedDocument(Base):
    """Persisted output of generated documents from templates."""

    __tablename__ = "generated_documents"
    __table_args__ = (
        Index("ix_generated_docs_company_id", "company_id"),
        Index("ix_generated_docs_template_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    variables: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="pdf", server_default=text("'pdf'"))
    file_path_or_url: Mapped[str] = mapped_column(String(500), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
