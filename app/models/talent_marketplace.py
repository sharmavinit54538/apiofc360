"""AI Talent Marketplace model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal
from app.db.base import Base
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.employee import Employee

class TalentMatch(Base):
    __tablename__ = "talent_matches"
    __table_args__ = (Index("ix_talent_matches_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    match_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PROJECT, INTERNAL_JOB, MENTOR, TRAINING, CAREER_OPPORTUNITY
    match_title: Mapped[str] = mapped_column(String(200), nullable=False)
    match_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0–100
    ai_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
