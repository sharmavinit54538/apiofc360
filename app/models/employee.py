"""Employee main database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, func, text, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee_address import EmployeeAddress
    from app.models.employee_document import EmployeeDocument
    from app.models.employee_education import EmployeeEducation
    from app.models.employee_experience import EmployeeExperience
    from app.models.employee_skill import EmployeeSkill
    from app.models.asset import Asset
    from app.models.employee_emergency_contact import EmployeeEmergencyContact
    from app.models.employee_bank_account import EmployeeBankAccount
    from app.models.employee_leave_policy import EmployeeLeavePolicy
    from app.models.employee_onboarding import EmployeeOnboarding
    from app.models.department import Department
    from app.models.company import Company


class Employee(Base):
    """Core employee record linked to a User account."""

    __tablename__ = "employees"
    __table_args__ = (
        Index("ix_employees_employee_id", "employee_id", unique=True),
        Index("ix_employees_personal_email", "personal_email", unique=True),
        Index("ix_employees_company_email", "company_email"),
        Index("ix_employees_company_id", "company_id"),
        Index("ix_employees_company_status", "company_id", "status", "is_deleted"),
        Index("ix_employees_company_department", "company_id", "department", "is_deleted"),
        Index("ix_employees_user_id", "user_id"),
        Index("ix_employees_status", "status"),
        Index("ix_employees_department", "department"),
        Index("ix_employees_is_deleted", "is_deleted"),
        Index("ix_employees_manager_id", "manager_id"),
        CheckConstraint("id != manager_id", name="ck_employees_manager_self_report"),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to auth user
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True,
    )

    # --------------- Basic Information ---------------
    employee_id: Mapped[str] = mapped_column(String(20), nullable=False)
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

    # --------------- Onboarding Additional Info ---------------
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    father_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mother_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spouse_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aadhaar_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    driving_license: Mapped[str | None] = mapped_column(String(30), nullable=True)
    voter_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    upi_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    esic_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    probation_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onboarding_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    employee_onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    employee_onboarding_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


    # --------------- Employment ---------------
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    team: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reporting_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
    )
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FULL_TIME", server_default=text("'FULL_TIME'"))
    employment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROBATION", server_default=text("'PROBATION'"))
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=100, server_default=text("100"))
    cost_center_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --------------- Salary ---------------
    ctc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    basic_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    hra: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    bonus: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    pf: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    esi: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    professional_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # --------------- Statutory Identity ---------------
    pan_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    uan_number: Mapped[str | None] = mapped_column(String(12), nullable=True)
    pf_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    esi_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --------------- System / Access ---------------
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="employee", server_default=text("'employee'"))
    leave_group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    # --------------- Role Metadata & Verification ---------------
    role_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))
    verification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING_ADMIN_CREATED",
        server_default=text("'PENDING_ADMIN_CREATED'"),
    )
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
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id], back_populates="employee", lazy="select")
    company: Mapped[Company | None] = relationship("Company", foreign_keys=[company_id], lazy="select")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], back_populates=None, lazy="select")
    inviter: Mapped[User | None] = relationship("User", foreign_keys=[invited_by], back_populates=None, lazy="select")
    reporting_manager: Mapped[Employee | None] = relationship(
        "Employee", remote_side="Employee.id", foreign_keys=[reporting_manager_id], lazy="select",
    )
    manager: Mapped[Employee | None] = relationship(
        "Employee", remote_side="Employee.id", foreign_keys=[manager_id], back_populates="direct_reports", lazy="select",
    )
    direct_reports: Mapped[list[Employee]] = relationship(
        "Employee", back_populates="manager", foreign_keys=[manager_id], lazy="select",
    )
    addresses: Mapped[list[EmployeeAddress]] = relationship("EmployeeAddress", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    documents: Mapped[list[EmployeeDocument]] = relationship("EmployeeDocument", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    education: Mapped[list[EmployeeEducation]] = relationship("EmployeeEducation", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    experience: Mapped[list[EmployeeExperience]] = relationship("EmployeeExperience", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    skills: Mapped[list[EmployeeSkill]] = relationship("EmployeeSkill", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    assets: Mapped[list[Asset]] = relationship("Asset", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    emergency_contacts: Mapped[list[EmployeeEmergencyContact]] = relationship("EmployeeEmergencyContact", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    bank_accounts: Mapped[list[EmployeeBankAccount]] = relationship("EmployeeBankAccount", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    leave_policies: Mapped[list[EmployeeLeavePolicy]] = relationship("EmployeeLeavePolicy", back_populates="employee", cascade="all, delete-orphan", lazy="select")
    onboarding_steps: Mapped[list[EmployeeOnboarding]] = relationship("EmployeeOnboarding", back_populates="employee", cascade="all, delete-orphan", lazy="select")

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    department_rel: Mapped[Department | None] = relationship(
        "Department", back_populates="employees", foreign_keys=[department_id], lazy="select"
    )

    @property
    def is_deactivated(self) -> bool:
        """Return True if the employee record is inactive, deactivated, archived, terminated, or deleted."""
        if not self.is_active or self.is_deleted:
            return True
        status_upper = (self.status or "").upper()
        if status_upper in {"DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED"}:
            return True
        emp_status_upper = (self.employment_status or "").upper()
        if emp_status_upper in {"EXITED", "TERMINATED"}:
            return True
        return False

