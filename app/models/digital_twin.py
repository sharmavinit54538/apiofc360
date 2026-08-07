"""AI Employee Digital Twin model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeDigitalTwin(Base):
    __tablename__ = "employee_digital_twins"
    __table_args__ = (Index("ix_digital_twin_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    skills_summary: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON
    performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0–100
    projects_summary: Mapped[str | None] = mapped_column(Text, nullable=True)       # JSON
    learning_progress: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON
    goals_summary: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON
    attendance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 0–100
    leave_utilization: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    productivity_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0–100
    career_growth_score: Mapped[int | None] = mapped_column(Integer, nullable=True) # 0–100
    certifications: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON
    feedback_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_performance_forecast: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
