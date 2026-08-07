"""EmployeeSkill model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeSkill(Base):
    """Skill records for an employee."""
    __tablename__ = "employee_skills"
    __table_args__ = (Index("ix_employee_skills_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(20), nullable=True)  # BEGINNER/INTERMEDIATE/EXPERT
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="skills")
