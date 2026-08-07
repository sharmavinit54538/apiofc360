"""Database model for Travel Requests."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class TravelRequest(Base):
    """Travel requests submitted by employees."""

    __tablename__ = "travel_requests"
    __table_args__ = (
        Index("ix_travel_requests_employee_id", "employee_id"),
        Index("ix_travel_requests_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    type: Mapped[str] = mapped_column(String(30), nullable=False, default="domestic")  # domestic, international
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    travel_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0.00)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")  # draft, manager-review, hr-review, finance-review, approved, rejected
    hotel: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transportation: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Store approval history/timeline as a JSON array of events
    # e.g., [{"stage": "draft", "at": "2026-07-18T...", "note": "..."}]
    history: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
