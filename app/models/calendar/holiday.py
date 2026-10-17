"""Holiday calendar database model."""

from __future__ import annotations

from datetime import date, datetime
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HolidayCalendar(Base):
    """Company holidays list."""

    __tablename__ = "holiday_calendar"
    __table_args__ = (
        UniqueConstraint("company_id", "holiday_date", "branch", name="uq_holiday_company_date_branch"),
        Index("ix_holiday_company_date", "company_id", "holiday_date"),
        Index("ix_holiday_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    holiday_name: Mapped[str] = mapped_column(String(150), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    holiday_type: Mapped[str] = mapped_column(String(50), nullable=False)  # NATIONAL, REGIONAL, COMPANY_HOLIDAY
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
