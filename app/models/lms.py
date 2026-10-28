"""Learning management, compliance assignment, progress, and certificates."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class LMSCourse(EnterpriseModelMixin, Base):
    __tablename__ = "lms_courses"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_lms_course_company_code"),
        Index("ix_lms_courses_company_status", "company_id", "status"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    target_departments: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    mandatory_for_compliance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    validity_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    modules: Mapped[list[LMSModule]] = relationship(
        "LMSModule", back_populates="course", cascade="all, delete-orphan", lazy="select",
    )


class LMSModule(EnterpriseModelMixin, Base):
    __tablename__ = "lms_modules"
    __table_args__ = (UniqueConstraint("course_id", "sequence_number", name="uq_lms_module_course_sequence"),)

    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("lms_courses.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    course: Mapped[LMSCourse] = relationship("LMSCourse", back_populates="modules", lazy="select")


class LMSEnrollment(EnterpriseModelMixin, Base):
    __tablename__ = "lms_enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "employee_id", name="uq_lms_enrollment_course_employee"),
        Index("ix_lms_enrollments_company_status", "company_id", "status"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("lms_courses.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignment_reason: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL", server_default=text("'MANUAL'"))
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ASSIGNED", server_default=text("'ASSIGNED'"))
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    module_progress: Mapped[list[LMSModuleProgress]] = relationship(
        "LMSModuleProgress", back_populates="enrollment", cascade="all, delete-orphan", lazy="select",
    )


class LMSModuleProgress(EnterpriseModelMixin, Base):
    __tablename__ = "lms_module_progress"
    __table_args__ = (UniqueConstraint("enrollment_id", "module_id", name="uq_lms_progress_enrollment_module"),)

    enrollment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("lms_enrollments.id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("lms_modules.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_STARTED", server_default=text("'NOT_STARTED'"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enrollment: Mapped[LMSEnrollment] = relationship("LMSEnrollment", back_populates="module_progress", lazy="select")


class LMSCertificate(EnterpriseModelMixin, Base):
    __tablename__ = "lms_certificates"
    __table_args__ = (
        UniqueConstraint("enrollment_id", name="uq_lms_certificate_enrollment"),
        UniqueConstraint("certificate_number", name="uq_lms_certificate_number"),
    )

    enrollment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("lms_enrollments.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(60), nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
