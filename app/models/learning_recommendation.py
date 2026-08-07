"""AI Learning Recommendation model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.employee import Employee

class LearningRecommendation(Base):
    __tablename__ = "learning_recommendations"
    __table_args__ = (Index("ix_learning_recs_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    target_skill_gap: Mapped[str] = mapped_column(String(200), nullable=False)
    recommended_courses: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON
    recommended_certifications: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_videos: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_books: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_projects: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_training: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
