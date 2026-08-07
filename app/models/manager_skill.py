"""ManagerSkill model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.manager import Manager


class ManagerSkill(Base):
    """Skill records for a manager."""

    __tablename__ = "manager_skills"
    __table_args__ = (Index("ix_manager_skills_manager_id", "manager_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("managers.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(20), nullable=True)  # BEGINNER/INTERMEDIATE/EXPERT
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    manager: Mapped[Manager] = relationship("Manager", back_populates="skills")
