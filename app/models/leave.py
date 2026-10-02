"""Database models for Leave Requests."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class LeaveRequest(Base):
    """Leave request applications submitted by employees."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("ix_leave_requests_employee_id", "employee_id"),
        Index("ix_leave_requests_status", "status"),
        Index("ix_leave_requests_dates", "start_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    
    leave_type: Mapped[str] = mapped_column(String(50), nullable=False)  # Sick Leave, Casual Leave, Vacation Leave
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING, APPROVED, REJECTED, CANCELLED
    
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    approved_by: Mapped[User | None] = relationship("User", lazy="select")

    @property
    def employee_name(self) -> str:
        """Resolve full name of the employee."""
        if self.employee:
            first = self.employee.first_name or ""
            last = self.employee.last_name or ""
            name = f"{first} {last}".strip()
            return name if name else "Employee"
        return "Employee"

    @property
    def department(self) -> str | None:
        """Resolve department name (not ID) of the employee."""
        if self.employee:
            dep_rel = getattr(self.employee, "department_rel", None)
            if dep_rel:
                dept_name = getattr(dep_rel, "department_name", None) or getattr(dep_rel, "name", None)
                if dept_name:
                    return dept_name
            return getattr(self.employee, "department", None)
        return None
