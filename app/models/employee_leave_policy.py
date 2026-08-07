"""EmployeeLeavePolicy model."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeLeavePolicy(Base):
    """Leave allocation per employee per leave type."""
    __tablename__ = "employee_leave_policies"
    __table_args__ = (Index("ix_employee_leave_policies_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(50), nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=0)
    used_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=0, server_default=text("0"))
    carry_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="leave_policies")
