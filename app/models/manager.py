"""Manager main database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index,
    Numeric, String, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.manager_address import ManagerAddress
    from app.models.manager_document import ManagerDocument
    from app.models.manager_education import ManagerEducation
    from app.models.manager_experience import ManagerExperience
    from app.models.manager_skill import ManagerSkill
    from app.models.manager_emergency_contact import ManagerEmergencyContact
    from app.models.department import Department
    from app.models.company import Company


class Manager(Base):
    """Core manager record linked to a User account."""

    __tablename__ = "managers"
    __table_args__ = (
        Index("ix_managers_manager_id", "manager_id", unique=True),
        Index("ix_managers_personal_email", "personal_email", unique=True),
        Index("ix_managers_company_email", "company_email"),
        Index("ix_managers_user_id", "user_id"),
        Index("ix_managers_status", "status"),
        Index("ix_managers_department", "department"),
        Index("ix_managers_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True,
    )

    # --------------- Basic Information ---------------
    manager_id: Mapped[str] = mapped_column(String(20), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    personal_email: Mapped[str] = mapped_column(String(255), nullable=False)
    company_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    alternate_phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --------------- Employment ---------------
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FULL_TIME", server_default=text("'FULL_TIME'"))
    employment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROBATION", server_default=text("'PROBATION'"))
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)
    probation_period_months: Mapped[int | None] = mapped_column(nullable=True)

    # --------------- Salary ---------------
    ctc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    basic_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    hra: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    bonus: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    pf: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    esi: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    professional_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # --------------- System / Access ---------------
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="manager", server_default=text("'manager'"))
    leave_group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    # --------------- Role Metadata & Verification ---------------
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # --------------- Activation ---------------
    activation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    activation_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    # --------------- Audit ---------------
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # --------------- Relationships ---------------
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id], back_populates="manager_profile", lazy="select")
    company: Mapped[Company | None] = relationship("Company", foreign_keys=[company_id], lazy="select")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], back_populates=None, lazy="select")
    inviter: Mapped[User | None] = relationship("User", foreign_keys=[invited_by], back_populates=None, lazy="select")
    addresses: Mapped[list[ManagerAddress]] = relationship("ManagerAddress", back_populates="manager", cascade="all, delete-orphan", lazy="select")
    documents: Mapped[list[ManagerDocument]] = relationship("ManagerDocument", back_populates="manager", cascade="all, delete-orphan", lazy="select")
    education: Mapped[list[ManagerEducation]] = relationship("ManagerEducation", back_populates="manager", cascade="all, delete-orphan", lazy="select")
    experience: Mapped[list[ManagerExperience]] = relationship("ManagerExperience", back_populates="manager", cascade="all, delete-orphan", lazy="select")
    skills: Mapped[list[ManagerSkill]] = relationship("ManagerSkill", back_populates="manager", cascade="all, delete-orphan", lazy="select")
    emergency_contacts: Mapped[list[ManagerEmergencyContact]] = relationship("ManagerEmergencyContact", back_populates="manager", cascade="all, delete-orphan", lazy="select")

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    department_rel: Mapped[Department | None] = relationship(
        "Department", back_populates="managers_profile", foreign_keys=[department_id], lazy="select"
    )

    # --------------- Onboarding & Parity Fields ---------------
    is_first_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    profile_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    office_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reporting_to: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL"), nullable=True,
    )
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)

    reporting_manager: Mapped[Manager | None] = relationship(
        "Manager", remote_side="Manager.id", foreign_keys=[reporting_to], lazy="select",
    )

    # --------------- Permissions & Access Settings ---------------
    can_approve_leave: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can approve leave"
    )
    can_approve_attendance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can approve attendance"
    )
    can_manage_employees: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can manage employees"
    )
    can_view_payroll: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can view payroll"
    )
    can_edit_departments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can edit departments"
    )
    can_invite_users: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can invite users"
    )
    can_manage_recruitment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can manage recruitment"
    )
    can_manage_performance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Can manage performance"
    )

    @property
    def reporting_manager_name(self) -> str:
        if self.reporting_manager:
            return f"{self.reporting_manager.first_name} {self.reporting_manager.last_name}".strip()
        return ""

    @property
    def team_size(self) -> int:
        return 0

    @property
    def last_active(self) -> datetime | None:
        return self.last_login

    @property
    def is_deactivated(self) -> bool:
        """Return True if the manager record is inactive, deactivated, archived, or deleted."""
        if not self.is_active or self.is_deleted:
            return True
        status_upper = (self.status or "").upper()
        if status_upper in {"DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED"}:
            return True
        emp_status_upper = (getattr(self, "employment_status", "") or "").upper()
        if emp_status_upper in {"EXITED", "TERMINATED"}:
            return True
        return False

