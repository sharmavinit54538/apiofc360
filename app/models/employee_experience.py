"""EmployeeExperience model."""
from __future__ import annotations
from decimal import Decimal
from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeExperience(Base):
    """Work experience records."""
    __tablename__ = "employee_experience"
    __table_args__ = (Index("ix_employee_experience_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    designation: Mapped[str] = mapped_column(String(150), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ctc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reason_for_leaving: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_certificate_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    relieving_letter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    salary_slip_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="experience")
