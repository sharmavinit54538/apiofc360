"""AI Career Path Generator model."""
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

class CareerPathPrediction(Base):
    __tablename__ = "career_path_predictions"
    __table_args__ = (Index("ix_career_path_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    predicted_next_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    promotion_timeline_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_roadmap: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    career_growth_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_opportunities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
