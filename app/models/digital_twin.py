"""AI Employee Digital Twin model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func
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


class OrgTwinSimulation(Base):
    """Persisted, reproducible organization scenario input and impact output."""
    __tablename__ = "org_twin_simulations"
    __table_args__ = (Index("ix_org_twin_simulations_company_created", "company_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    baseline_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
