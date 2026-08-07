"""JobTemplate database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class JobTemplate(Base):
    """Reusable job description templates."""

    __tablename__ = "job_templates"
    __table_args__ = (
        Index("ix_job_template_dept", "department"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FULL_TIME")

    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills_required: Mapped[list | None] = mapped_column(JSON, nullable=True)

    min_experience: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    creator: Mapped["User | None"] = relationship("User", lazy="select")
