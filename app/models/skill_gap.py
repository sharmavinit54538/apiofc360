"""AI Skill Gap Analysis models."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class SkillGapAnalysis(Base):
    __tablename__ = "skill_gap_analyses"
    __table_args__ = (Index("ix_skill_gap_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    target_role: Mapped[str] = mapped_column(String(100), nullable=False)
    current_skills: Mapped[str] = mapped_column(Text, nullable=False)   # JSON list
    required_skills: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    missing_skills: Mapped[str] = mapped_column(Text, nullable=False)   # JSON list
    learning_roadmap: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_courses: Mapped[str | None] = mapped_column(Text, nullable=True)
    certification_suggestions: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    hiring_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
