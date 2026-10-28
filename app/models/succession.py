"""Critical-role succession slates and development planning."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class CriticalRole(EnterpriseModelMixin, Base):
    __tablename__ = "succession_critical_roles"
    __table_args__ = (
        UniqueConstraint("company_id", "title", "department", name="uq_succession_role_title_department"),
        Index("ix_succession_roles_company_risk", "company_id", "risk_level"),
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    incumbent_employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    vacancy_risk_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=50)
    business_impact_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=50)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"))

    successors: Mapped[list[SuccessorSlate]] = relationship(
        "SuccessorSlate", back_populates="role", cascade="all, delete-orphan", lazy="select",
    )


class SuccessorSlate(EnterpriseModelMixin, Base):
    __tablename__ = "succession_slates"
    __table_args__ = (
        UniqueConstraint("role_id", "employee_id", name="uq_succession_slate_role_employee"),
        Index("ix_succession_slates_company_readiness", "company_id", "readiness_category"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("succession_critical_roles.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    performance_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    potential_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    skill_coverage_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    readiness_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    readiness_category: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    role: Mapped[CriticalRole] = relationship("CriticalRole", back_populates="successors", lazy="select")
    development_actions: Mapped[list[SuccessionDevelopmentAction]] = relationship(
        "SuccessionDevelopmentAction", back_populates="slate", cascade="all, delete-orphan", lazy="select",
    )


class SuccessionDevelopmentAction(EnterpriseModelMixin, Base):
    __tablename__ = "succession_development_actions"
    __table_args__ = (Index("ix_succession_actions_company_status", "company_id", "status"),)

    slate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("succession_slates.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_STARTED", server_default=text("'NOT_STARTED'"))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    slate: Mapped[SuccessorSlate] = relationship("SuccessorSlate", back_populates="development_actions", lazy="select")
