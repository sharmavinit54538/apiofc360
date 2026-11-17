"""Database models for Enterprise Performance Management AI.

Includes cycles, KPI/goal trackers, OKRs, and AI performance evaluation records.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Numeric, UniqueConstraint, func, text, JSON
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


# ---------------------------------------------------------------------------
# Batch 6: tenant-safe 360 reviews, calibration, and promotion workflows
# ---------------------------------------------------------------------------
from app.models.enterprise_common import EnterpriseModelMixin


class PerformanceCycleV2(EnterpriseModelMixin, Base):
    __tablename__ = "performance_cycles_v2"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_performance_cycle_v2_company_name"),
        Index("ix_performance_cycles_v2_company_status", "company_id", "status"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    bell_curve_targets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))

    reviews: Mapped[list[PerformanceReview360]] = relationship(
        "PerformanceReview360", back_populates="cycle", cascade="all, delete-orphan", lazy="select",
    )


class PerformanceReview360(EnterpriseModelMixin, Base):
    __tablename__ = "performance_reviews_360"
    __table_args__ = (
        UniqueConstraint("cycle_id", "employee_id", "reviewer_id", "review_type", name="uq_performance_360_reviewer"),
        Index("ix_performance_360_company_employee", "company_id", "employee_id"),
    )

    cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_cycles_v2.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    review_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    calibrated_rating: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cycle: Mapped[PerformanceCycleV2] = relationship("PerformanceCycleV2", back_populates="reviews", lazy="select")


class PerformanceCalibrationRun(EnterpriseModelMixin, Base):
    __tablename__ = "performance_calibration_runs"
    __table_args__ = (Index("ix_performance_calibration_company_cycle", "company_id", "cycle_id"),)

    cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_cycles_v2.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_PROGRESS", server_default=text("'IN_PROGRESS'"))
    target_distribution: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    started_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromotionApproval(EnterpriseModelMixin, Base):
    __tablename__ = "performance_promotion_approvals"
    __table_args__ = (Index("ix_promotion_approvals_company_status", "company_id", "status"),)

    cycle_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_cycles_v2.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    current_grade: Mapped[str] = mapped_column(String(40), nullable=False)
    target_grade: Mapped[str] = mapped_column(String(40), nullable=False)
    target_band_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("compensation_bands.id", ondelete="SET NULL"), nullable=True)
    recommended_increment_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_MANAGER", server_default=text("'PENDING_MANAGER'"))
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manager_approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    hr_approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PerformanceFeedback(EnterpriseModelMixin, Base):
    __tablename__ = "performance_feedback"
    __table_args__ = (
        Index("ix_performance_feedback_employee_id", "employee_id"),
        Index("ix_performance_feedback_review_id", "review_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    review_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_reviews.id", ondelete="SET NULL"), nullable=True)
    author_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)  # employee, manager, peer, self
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    strengths: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_areas: Mapped[str] = mapped_column(Text, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    author: Mapped[User] = relationship("User", lazy="select")
    review: Mapped[PerformanceReview | None] = relationship("PerformanceReview", lazy="select")


class PerformanceReward(EnterpriseModelMixin, Base):
    __tablename__ = "performance_rewards"
    __table_args__ = (
        Index("ix_performance_rewards_employee_id", "employee_id"),
        Index("ix_performance_rewards_review_id", "review_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    review_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_reviews.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reward_type: Mapped[str] = mapped_column(String(30), nullable=False)  # recognition, award, bonus, promotion, other
    monetary_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review: Mapped[PerformanceReview | None] = relationship("PerformanceReview", lazy="select")


class TrainingCourse(EnterpriseModelMixin, Base):
    __tablename__ = "training_courses"
    __table_args__ = (
        Index("ix_training_courses_company_id", "company_id"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class TrainingAssignment(EnterpriseModelMixin, Base):
    __tablename__ = "training_assignments"
    __table_args__ = (
        Index("ix_training_assignments_employee_id", "employee_id"),
        Index("ix_training_assignments_training_id", "training_id"),
        Index("ix_training_assignments_status", "status"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    training_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("training_courses.id", ondelete="CASCADE"), nullable=False)
    assigned_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium", server_default=text("'medium'"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned", server_default=text("'assigned'"))  # assigned, in_progress, completed, cancelled
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("performance_reviews.id", ondelete="SET NULL"), nullable=True)

    training: Mapped[TrainingCourse] = relationship("TrainingCourse", lazy="select")
