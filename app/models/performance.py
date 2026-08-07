"""Database models for Enterprise Performance Management AI.

Includes cycles, KPI/goal trackers, OKRs, and AI performance evaluation records.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Numeric, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class PerformanceReviewCycle(Base):
    """Annual, semi-annual, or quarterly company performance evaluation cycles."""

    __tablename__ = "performance_review_cycles"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))  # ACTIVE, COMPLETED

    reviews: Mapped[list[PerformanceReview]] = relationship("PerformanceReview", back_populates="cycle", cascade="all, delete-orphan", lazy="select")


class EmployeePerformanceGoal(Base):
    """Goal Tracking and OKRs set for individual employees."""

    __tablename__ = "employee_performance_goals"
    __table_args__ = (
        Index("ix_performance_goals_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_value: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "100%", "500000 Revenue"
    current_value: Mapped[str] = mapped_column(String(100), nullable=False, default="0")
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING, IN_PROGRESS, ACHIEVED, MISSED

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class PerformanceReview(Base):
    """Aggregate individual self-reviews, 360 feedback reviews, and AI-predicted outcomes."""

    __tablename__ = "performance_reviews"
    __table_args__ = (
        Index("ix_performance_reviews_cycle_id", "cycle_id"),
        Index("ix_performance_reviews_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_review_cycles.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    self_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    reviewer_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    
    # AI Evaluation results
    ai_overall_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    ai_review_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_recommendation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    salary_increment_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    feedback_360: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"peer_rating_average": 4.2, "peer_notes": "Great collaborator"}
    skill_gap_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"identified_gaps": ["Kubernetes", "System Design"]}
    learning_recommendations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)  # [{"course": "Advanced Docker", "platform": "Coursera"}]

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))  # DRAFT, SUBMITTED, COMPLETED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    cycle: Mapped[PerformanceReviewCycle] = relationship("PerformanceReviewCycle", back_populates="reviews")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    reviewer: Mapped[User | None] = relationship("User", lazy="select")
