"""Database model for daily Face Attendance logs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, String, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.company import Company


class Attendance(Base):
    """Daily face attendance log record."""

    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_employee_date_attendance"),
        Index("ix_attendances_employee_id", "employee_id"),
        Index("ix_attendances_company_id", "company_id"),
        Index("ix_attendances_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    check_in_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    check_out_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    face_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checkout_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    working_hours: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    company: Mapped[Company | None] = relationship("Company", lazy="select")
