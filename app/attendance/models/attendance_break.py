"""Database model for employee attendance break tracking sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.attendance.models.attendance import Attendance
    from app.models.company import Company
    from app.models.employee import Employee


class AttendanceBreak(Base):
    """Tracks discrete break sessions during an employee's daily attendance."""

    __tablename__ = "attendance_breaks"
    __table_args__ = (
        Index("ix_attendance_breaks_attendance_id", "attendance_id"),
        Index("ix_attendance_breaks_employee_id", "employee_id"),
        Index("ix_attendance_breaks_company_id", "company_id"),
        Index("ix_attendance_breaks_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attendance_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendances.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )

    break_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    break_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[Optional[float]] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE | COMPLETED
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    attendance: Mapped[Attendance] = relationship("Attendance", back_populates="breaks", lazy="select")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    company: Mapped[Optional[Company]] = relationship("Company", lazy="select")
