"""EmployeeAddress model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeAddress(Base):
    """Stores current and permanent addresses for an employee."""
    __tablename__ = "employee_addresses"
    __table_args__ = (Index("ix_employee_addresses_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    address_type: Mapped[str] = mapped_column(String(20), nullable=False)  # CURRENT / PERMANENT
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="India", server_default=text("'India'"))
    pincode: Mapped[str] = mapped_column(String(10), nullable=False)
    is_same_as_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="addresses")
