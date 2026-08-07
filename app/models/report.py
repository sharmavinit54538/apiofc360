"""Database model for Reports and Analytics."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    """Generated and scheduled reports."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_status", "status"),
        Index("ix_reports_type", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # employee, payroll, attendance, leave, recruitment, travel, compliance, audit
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")  # pending, running, completed, failed
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")  # pdf, csv, excel
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(30), nullable=True)  # none, daily, weekly, monthly

    # Storage details
    file_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_size_kb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
