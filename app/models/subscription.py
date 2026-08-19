"""Subscription database model."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import String, DateTime, func, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Subscription(Base):
    """Company Subscription in PostgreSQL."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(100), nullable=True, default="Starter")
    access_status: Mapped[str] = mapped_column(String(50), nullable=True, default="ACTIVE")
    access_type: Mapped[str] = mapped_column(String(50), nullable=True, default="FULL")
    payment_status: Mapped[str] = mapped_column(String(50), nullable=True, default="UNPAID")
    access_source: Mapped[str] = mapped_column(String(50), nullable=True, default="SUPER_ADMIN")
    access_granted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    access_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_grant_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspension_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    company = relationship("Company", backref="subscriptions", lazy="selectin")
