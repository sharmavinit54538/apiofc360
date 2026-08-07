"""Recruitment Management database models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, Time, func, text, JSON,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee import Employee


class Job(Base):
    """Job posting record."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_slug", "slug", unique=True),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FULL_TIME", server_default=text("'FULL_TIME'"))

    experience_required: Mapped[str | None] = mapped_column(String(100), nullable=True)
    min_experience: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)

    min_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    location: Mapped[str] = mapped_column(String(100), nullable=False)
    vacancies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)

    application_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    interview_process_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    # Audit
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")
    skills: Mapped[list[JobSkill]] = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan", lazy="select")
    applications: Mapped[list[Application]] = relationship("Application", back_populates="job", cascade="all, delete-orphan", lazy="select")


class JobSkill(Base):
    """Required skills for a job posting."""

    __tablename__ = "job_skills"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="skills")


class Application(Base):
    """Candidate job application submission."""

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_company_id", "company_id"),
        Index("ix_applications_candidate_id", "candidate_id"),
        Index("ix_applications_job_id", "job_id"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_email", "email"),
        Index("ix_applications_company_status", "company_id", "status"),
        Index("ix_applications_job_status", "job_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)

    # Candidate details
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)

    current_company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    current_designation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    current_ctc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_ctc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    notice_period: Mapped[str | None] = mapped_column(String(50), nullable=True)

    highest_qualification: Mapped[str | None] = mapped_column(String(150), nullable=True)
    experience_years: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0.0)

    linkedin_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    declaration_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="APPLIED", server_default=text("'APPLIED'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    job: Mapped[Job] = relationship("Job", back_populates="applications")
    candidate: Mapped[Candidate | None] = relationship("Candidate", back_populates="applications", lazy="select")
    documents: Mapped[list[ApplicationDocument]] = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan", lazy="select")
    interviews: Mapped[list[Interview]] = relationship("Interview", back_populates="application", cascade="all, delete-orphan", lazy="select")
    offers: Mapped[list[Offer]] = relationship("Offer", back_populates="application", cascade="all, delete-orphan", lazy="select")


class ApplicationDocument(Base):
    """Documents submitted by candidate (resume)."""

    __tablename__ = "application_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False, default="RESUME", server_default=text("'RESUME'"))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    application: Mapped[Application] = relationship("Application", back_populates="documents")


class Interview(Base):
    """An interview lifecycle for a candidate application."""

    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SCHEDULED", server_default=text("'SCHEDULED'"))
    current_round_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    application: Mapped[Application] = relationship("Application", back_populates="interviews")
    rounds: Mapped[list[InterviewRound]] = relationship("InterviewRound", back_populates="interview", cascade="all, delete-orphan", lazy="select")
    schedules: Mapped[list[InterviewSchedule]] = relationship("InterviewSchedule", back_populates="interview", cascade="all, delete-orphan", lazy="select")


class InterviewRound(Base):
    """Configurable interview rounds (Technical Round 1, Technical Round 2, HR etc.)."""

    __tablename__ = "interview_rounds"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False)
    round_name: Mapped[str] = mapped_column(String(100), nullable=False)
    round_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    interviewer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    conducted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    interview: Mapped[Interview] = relationship("Interview", back_populates="rounds")
    schedules: Mapped[list[InterviewSchedule]] = relationship("InterviewSchedule", back_populates="round", cascade="all, delete-orphan", lazy="select")


class InterviewSchedule(Base):
    """Date, Time, and Venue/URL slot booked for a round."""

    __tablename__ = "interview_schedules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False)
    round_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_rounds.id", ondelete="CASCADE"), nullable=False)

    interview_date: Mapped[date] = mapped_column(Date, nullable=False)
    interview_time: Mapped[Time] = mapped_column(Time, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="ONLINE")  # ONLINE/OFFLINE
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    office_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    interview: Mapped[Interview] = relationship("Interview", back_populates="schedules")
    round: Mapped[InterviewRound] = relationship("InterviewRound", back_populates="schedules")


class Offer(Base):
    """Candidate job offer details."""

    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)

    ctc: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    offer_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SENT", server_default=text("'SENT'"))

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    application: Mapped[Application] = relationship("Application", back_populates="offers")
    documents: Mapped[list[OfferDocument]] = relationship("OfferDocument", back_populates="offer", cascade="all, delete-orphan", lazy="select")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")


class OfferDocument(Base):
    """Linked files for released offer letter."""

    __tablename__ = "offer_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    offer: Mapped[Offer] = relationship("Offer", back_populates="documents")


class CareerPageSetting(Base):
    """Global configuration settings for careers page."""

    __tablename__ = "career_page_settings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(100), nullable=False, default="Aurix", server_default=text("'Aurix'"))
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    theme_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#0f172a", server_default=text("'#0f172a'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Candidate(Base):
    """Master Candidate Profile."""

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    years_experience: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0.0)
    current_company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    current_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    expected_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    notice_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resume_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="DIRECT")
    is_talent_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("recruitment_vendors.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    applications: Mapped[list[Application]] = relationship("Application", back_populates="candidate", cascade="all, delete-orphan", lazy="select")
    notes: Mapped[list[CandidateCrmNote]] = relationship("CandidateCrmNote", back_populates="candidate", cascade="all, delete-orphan", lazy="select")
    vendor: Mapped[RecruitmentVendor | None] = relationship("RecruitmentVendor", back_populates="candidates", lazy="select")


class JobRequisition(Base):
    """Job requisition pre-approval flow."""

    __tablename__ = "job_requisitions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    vacancies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_experience: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED
    requested_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    requester: Mapped[User] = relationship("User", foreign_keys=[requested_by], lazy="select")
    approver: Mapped[User | None] = relationship("User", foreign_keys=[approved_by], lazy="select")


class RecruitmentVendor(Base):
    """Recruitment Agency/Vendor details."""

    __tablename__ = "recruitment_vendors"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, INACTIVE
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    candidates: Mapped[list[Candidate]] = relationship("Candidate", back_populates="vendor", lazy="select")


class ScorecardTemplate(Base):
    """Interview evaluation criteria templates."""

    __tablename__ = "scorecard_templates"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)  # List of criteria e.g. [{"id": "c1", "name": "Technical Depth", "weight": 0.5}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ScorecardSubmission(Base):
    """Actual rating filled by interviewer."""

    __tablename__ = "scorecard_submissions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_round_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_rounds.id", ondelete="CASCADE"), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scores: Mapped[dict] = mapped_column(JSON, nullable=False)  # Criterion ID -> Score (1-5)
    overall_recommendation: Mapped[str] = mapped_column(String(20), nullable=False)  # STRONG_HIRE, HIRE, MAYBE, REJECT
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    round: Mapped[InterviewRound] = relationship("InterviewRound", lazy="select")
    submitter: Mapped[User] = relationship("User", lazy="select")


class CandidateReferral(Base):
    """Employee referral tracker."""

    __tablename__ = "candidate_referrals"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUBMITTED")  # SUBMITTED, UNDER_REVIEW, HIRED, REJECTED
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    reward_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING, PAID, VOIDED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    candidate: Mapped[Candidate] = relationship("Candidate", lazy="select")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    job: Mapped[Job | None] = relationship("Job", lazy="select")


class RecruitmentAutomationRule(Base):
    """Rule engine for automatic actions in recruitment."""

    __tablename__ = "recruitment_automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_event: Mapped[str] = mapped_column(String(50), nullable=False)  # APPLICATION_RECEIVED, STAGE_CHANGED, INTERVIEW_COMPLETED
    conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # conditions configuration
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)  # MOVE_STAGE, SEND_EMAIL, NOTIFY_RECRUITER
    action_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # action parameters
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CandidateCrmNote(Base):
    """CRM candidate touchpoints & follow-ups."""

    __tablename__ = "candidate_crm_notes"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="note", server_default="note")
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    candidate: Mapped[Candidate] = relationship("Candidate", back_populates="notes")
    author: Mapped[User] = relationship("User", lazy="select")


class RecruitmentNotification(Base):
    """Recruitment module notification feed."""

    __tablename__ = "recruitment_notifications"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship("User", lazy="select")


class JobPublishChannel(Base):
    """Job publishing channel status."""

    __tablename__ = "job_publish_channels"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(50), nullable=False)  # career_site, public_link, internal_portal
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    unique_key: Mapped[str | None] = mapped_column(String(100), nullable=True)

    job: Mapped[Job] = relationship("Job", lazy="select")
