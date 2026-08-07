"""AI Employee Risk Engine model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeRiskAssessment(Base):
    __tablename__ = "employee_risk_assessments"
    __table_args__ = (Index("ix_risk_assessments_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    resignation_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0–100
    burnout_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 0–100
    performance_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0–100
    compliance_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 0–100
    engagement_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 0–100
    overall_risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")  # LOW, MEDIUM, HIGH, CRITICAL
    risk_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_actions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
