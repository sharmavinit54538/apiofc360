"""Production-ready Service Layer for HR Admin Onboarding.

Provides comprehensive transaction-safe business logic for:
1. Admin Profile
2. Company Setup
3. Organization & Departments
4. Work Schedule & Leave Policies
5. Employee Invitations (Individual Only)
6. Review & Activate
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_invitation import EmployeeInvitation
from app.models.onboarding import CompanySettings, Designation, LeavePolicy, OnboardingProgress, Shift
from app.models.user import User
from app.schemas.onboarding import (
    DepartmentCreateInput,
    DepartmentItemResponse,
    DepartmentUpdateInput,
    DesignationCreateInput,
    DesignationItemResponse,
    DesignationUpdateInput,
    HRAdminProfileInput,
    HRAdminProfileResponse,
    IndividualInvitationInput,
    InvitationResponse,
    LeavePolicyCreateInput,
    LeavePolicyResponse,
    LeavePolicyUpdateInput,
    OnboardingProgressResponse,
    OnboardingReviewResponse,
    OnboardingStatusResponse,
    OrganizationInput,
    OrganizationResponse,
    WorkScheduleInput,
    WorkScheduleResponse,
)

logger = logging.getLogger(__name__)


class HRAdminOnboardingService:
    """Encapsulates all HR Admin onboarding business operations with multi-tenant isolation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: Ensure Organization Access
    # ─────────────────────────────────────────────────────────────────────────

    async def get_company(self, company_id: uuid.UUID) -> Company:
        """Load company with tenant isolation or raise 404."""
        result = await self.session.execute(select(Company).where(Company.id == company_id))
        company = result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        return company

    async def get_user(self, user_id: uuid.UUID) -> User:
        """Load user or raise 404."""
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")
        return user

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 1: Admin Profile
    # ─────────────────────────────────────────────────────────────────────────

    async def get_admin_profile(self, user_id: uuid.UUID, company_id: uuid.UUID) -> HRAdminProfileResponse:
        """Retrieve HR Admin profile data."""
        user = await self.get_user(user_id)

        # Cross-organization security check
        if user.company_id and user.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access to other organization data is forbidden.")

        # Check linked Employee record if present
        emp_result = await self.session.execute(
            select(Employee).where(
                (Employee.user_id == user.id) |
                (func.lower(Employee.company_email) == (user.email or "").lower().strip())
            )
        )
        emp = emp_result.scalars().first()

        first_name = ""
        last_name = ""
        if emp and emp.first_name:
            first_name = emp.first_name
            last_name = emp.last_name or ""
        elif user.name:
            parts = user.name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

        designation = (emp.designation if emp else None) or "HR Admin"
        photo_url = (emp.profile_photo_url if emp else None) or getattr(user, "avatar_url", None)

        return HRAdminProfileResponse(
            first_name=first_name,
            last_name=last_name,
            work_email=user.email,
            phone_number=user.phone or "",
            job_title=designation,
            profile_photo_url=photo_url,
            organization_id=str(company_id) if company_id else None,
        )

    async def update_admin_profile(
        self, user_id: uuid.UUID, company_id: uuid.UUID, payload: HRAdminProfileInput
    ) -> HRAdminProfileResponse:
        """Update HR Admin profile and associate with organization."""
        user = await self.get_user(user_id)

        # Enforce organization association
        if user.company_id and user.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify admin profile for a different organization.")

        if not user.company_id:
            user.company_id = company_id

        clean_first = payload.first_name.strip()
        clean_last = payload.last_name.strip()
        clean_phone = payload.phone_number.strip()
        user.name = f"{clean_first} {clean_last}".strip()
        user.phone = clean_phone

        # Upsert or link Employee profile for HR Admin
        emp_result = await self.session.execute(
            select(Employee).where(
                (Employee.user_id == user.id) |
                (func.lower(Employee.company_email) == (user.email or "").lower().strip())
            )
        )
        emp = emp_result.scalars().first()

        if emp:
            emp.first_name = clean_first
            emp.last_name = clean_last
            emp.phone = clean_phone
            if payload.job_title:
                emp.designation = payload.job_title
            if payload.profile_photo_url:
                emp.profile_photo_url = payload.profile_photo_url
            if not emp.company_id:
                emp.company_id = company_id
        else:
            new_emp = Employee(
                id=uuid.uuid4(),
                company_id=company_id,
                user_id=user.id,
                employee_id=f"EMP-ADM-{secrets.token_hex(3).upper()}",
                first_name=clean_first,
                last_name=clean_last,
                company_email=user.email,
                personal_email=user.email,
                phone=clean_phone,
                designation=payload.job_title or "HR Admin",
                department="Management",
                profile_photo_url=payload.profile_photo_url,
                employment_type="FULL_TIME",
                employment_status="CONFIRMED",
                status="ACTIVE",
                role="hr_admin",
                is_active=True,
                created_by=user.id,
            )
            self.session.add(new_emp)

        # Update snapshot on company
        company = await self.get_company(company_id)
        prof = company.company_profile or {}
        prof["admin_profile"] = {
            "first_name": clean_first,
            "last_name": clean_last,
            "work_email": user.email,
            "phone_number": clean_phone,
            "job_title": payload.job_title,
            "profile_photo_url": payload.profile_photo_url,
        }
        company.company_profile = prof
        flag_modified(company, "company_profile")

        # Mark admin step in progress
        progress = await self.get_or_create_progress(company_id, user_id)
        progress.admin_completed = True
        if progress.current_step < 2:
            progress.current_step = 2
        progress.status = "in_progress"
        await self._sync_completed_steps(progress)

        await self.session.commit()

        return HRAdminProfileResponse(
            first_name=clean_first,
            last_name=clean_last,
            work_email=user.email,
            phone_number=clean_phone,
            job_title=payload.job_title or "HR Admin",
            profile_photo_url=payload.profile_photo_url,
            organization_id=str(company_id),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 2: Company / Organization Setup
    # ─────────────────────────────────────────────────────────────────────────

    async def get_organization(self, company_id: uuid.UUID) -> OrganizationResponse:
        """Retrieve organization details."""
        company = await self.get_company(company_id)
        prof = company.company_profile or {}

        return OrganizationResponse(
            id=str(company.id),
            company_name=company.name,
            industry=prof.get("industry"),
            company_size=prof.get("company_size") or prof.get("companySize"),
            website=prof.get("website"),
            country=prof.get("country", "India"),
            address=prof.get("address"),
            city=prof.get("city"),
            state=prof.get("state"),
            zip_code=prof.get("zip_code") or prof.get("zipCode"),
            cin=prof.get("cin"),
            gst_number=prof.get("gst_number") or prof.get("gstNumber"),
            company_logo_url=prof.get("company_logo_url") or prof.get("company_logo") or prof.get("logo"),
            company_stamp_url=prof.get("company_stamp_url") or prof.get("company_stamp") or prof.get("stamp"),
            status=getattr(company, "status", "PENDING") or "PENDING",
            onboarding_completed=bool(company.onboarding_completed),
        )

    async def create_organization(self, user_id: uuid.UUID, payload: OrganizationInput) -> OrganizationResponse:
        """Create a new organization for the HR Admin."""
        user = await self.get_user(user_id)
        clean_name = payload.company_name.strip()

        # If user already has a company, update it instead of creating duplicates
        if user.company_id:
            existing = await self.get_company(user.company_id)
            if existing:
                return await self.update_organization(user.company_id, payload)

        company = Company(
            id=uuid.uuid4(),
            name=clean_name,
            onboarding_completed=False,
            onboarding_step=2,
            company_profile=payload.model_dump(),
        )
        setattr(company, "status", "PENDING")
        self.session.add(company)
        await self.session.flush()

        user.company_id = company.id
        self.session.add(user)

        progress = await self.get_or_create_progress(company.id, user_id)
        progress.company_completed = True
        if progress.current_step < 3:
            progress.current_step = 3
        progress.status = "in_progress"
        await self._sync_completed_steps(progress)

        await self.session.commit()
        return await self.get_organization(company.id)

    async def update_organization(self, company_id: uuid.UUID, payload: OrganizationInput) -> OrganizationResponse:
        """Update organization details."""
        company = await self.get_company(company_id)
        clean_name = payload.company_name.strip()

        company.name = clean_name
        prof = company.company_profile or {}
        prof.update(payload.model_dump())
        prof["company_name"] = clean_name
        prof["companyName"] = clean_name
        company.company_profile = prof
        flag_modified(company, "company_profile")

        progress = await self.get_or_create_progress(company_id)
        progress.company_completed = True
        if progress.current_step < 3:
            progress.current_step = 3
        progress.status = "in_progress"
        await self._sync_completed_steps(progress)

        await self.session.commit()
        return await self.get_organization(company_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3: Departments CRUD (Strictly Isolated, No Demo Records)
    # ─────────────────────────────────────────────────────────────────────────

    async def create_department(
        self, company_id: uuid.UUID, user_id: uuid.UUID, payload: DepartmentCreateInput
    ) -> DepartmentItemResponse:
        """Create department for an organization. Prevents duplicates and demo data."""
        clean_name = payload.department_name.strip()
        clean_code = (payload.department_code or "").strip()
        if not clean_code:
            clean_code = "".join(filter(str.isalnum, clean_name.upper()))[:6] or "DEPT"

        # Duplicate check within company
        dup_check = await self.session.execute(
            select(Department).where(
                Department.company_id == company_id,
                (func.lower(Department.department_name) == clean_name.lower()) |
                (func.lower(Department.department_code) == clean_code.lower())
            )
        )
        if dup_check.scalars().first():
            raise ConflictException(message=f"Department '{clean_name}' or code '{clean_code}' already exists in this organization.")

        dept = Department(
            id=uuid.uuid4(),
            company_id=company_id,
            department_name=clean_name,
            department_code=clean_code,
            description=payload.description or "",
            location=payload.location or "Headquarters",
            status="ACTIVE",
            created_by=user_id,
        )
        self.session.add(dept)

        progress = await self.get_or_create_progress(company_id, user_id)
        progress.departments_completed = True
        await self._sync_completed_steps(progress)

        await self.session.commit()
        return DepartmentItemResponse(
            id=str(dept.id),
            company_id=str(dept.company_id),
            department_name=dept.department_name,
            department_code=dept.department_code,
            description=dept.description,
            location=dept.location,
            status=dept.status,
            employee_count=0,
            created_at=dept.created_at.isoformat() if dept.created_at else None,
        )

    async def list_departments(self, company_id: uuid.UUID) -> List[DepartmentItemResponse]:
        """List departments belonging ONLY to this organization."""
        stmt = select(Department).where(
            Department.company_id == company_id,
            Department.is_deleted.is_(False)
        ).order_by(Department.department_name)
        res = await self.session.execute(stmt)
        items = res.scalars().all()

        return [
            DepartmentItemResponse(
                id=str(d.id),
                company_id=str(d.company_id),
                department_name=d.department_name,
                department_code=d.department_code,
                description=d.description,
                location=d.location,
                status=d.status,
                employee_count=0,
                created_at=d.created_at.isoformat() if d.created_at else None,
            )
            for d in items
        ]

    async def get_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> DepartmentItemResponse:
        """Get department by ID with strict organization-level ownership check."""
        stmt = select(Department).where(
            Department.id == department_id,
            Department.company_id == company_id,
            Department.is_deleted.is_(False)
        )
        res = await self.session.execute(stmt)
        dept = res.scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")

        return DepartmentItemResponse(
            id=str(dept.id),
            company_id=str(dept.company_id),
            department_name=dept.department_name,
            department_code=dept.department_code,
            description=dept.description,
            location=dept.location,
            status=dept.status,
            employee_count=0,
            created_at=dept.created_at.isoformat() if dept.created_at else None,
        )

    async def update_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID, payload: DepartmentUpdateInput
    ) -> DepartmentItemResponse:
        """Update department with organization-level isolation."""
        stmt = select(Department).where(
            Department.id == department_id,
            Department.company_id == company_id,
            Department.is_deleted.is_(False)
        )
        res = await self.session.execute(stmt)
        dept = res.scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")

        if payload.department_name:
            clean_name = payload.department_name.strip()
            dup = await self.session.execute(
                select(Department).where(
                    Department.company_id == company_id,
                    Department.id != department_id,
                    func.lower(Department.department_name) == clean_name.lower()
                )
            )
            if dup.scalars().first():
                raise ConflictException(message=f"Department '{clean_name}' already exists in this organization.")
            dept.department_name = clean_name

        if payload.department_code:
            dept.department_code = payload.department_code.strip()
        if payload.description is not None:
            dept.description = payload.description
        if payload.location:
            dept.location = payload.location
        if payload.status:
            dept.status = payload.status

        await self.session.commit()
        return await self.get_department(company_id, department_id)

    async def delete_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> bool:
        """Delete department belonging to organization."""
        stmt = select(Department).where(Department.id == department_id, Department.company_id == company_id)
        res = await self.session.execute(stmt)
        dept = res.scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")

        await self.session.delete(dept)
        await self.session.commit()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3: Designations CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def create_designation(self, company_id: uuid.UUID, payload: DesignationCreateInput) -> DesignationItemResponse:
        """Create designation for organization with duplicate prevention."""
        clean_name = payload.name.strip()
        dup = await self.session.execute(
            select(Designation).where(
                Designation.company_id == company_id,
                func.lower(Designation.name) == clean_name.lower()
            )
        )
        if dup.scalars().first():
            raise ConflictException(message=f"Designation '{clean_name}' already exists in this organization.")

        desig = Designation(
            id=uuid.uuid4(),
            company_id=company_id,
            name=clean_name,
            description=payload.description or f"Role designation for {clean_name}",
        )
        self.session.add(desig)

        progress = await self.get_or_create_progress(company_id)
        progress.designations_completed = True
        await self._sync_completed_steps(progress)

        await self.session.commit()
        return DesignationItemResponse(
            id=str(desig.id),
            company_id=str(desig.company_id),
            name=desig.name,
            description=desig.description,
            created_at=desig.created_at.isoformat() if desig.created_at else None,
        )

    async def list_designations(self, company_id: uuid.UUID) -> List[DesignationItemResponse]:
        """List designations belonging ONLY to organization."""
        res = await self.session.execute(
            select(Designation).where(Designation.company_id == company_id).order_by(Designation.name)
        )
        return [
            DesignationItemResponse(
                id=str(d.id),
                company_id=str(d.company_id),
                name=d.name,
                description=d.description,
                created_at=d.created_at.isoformat() if d.created_at else None,
            )
            for d in res.scalars().all()
        ]

    async def get_designation(self, company_id: uuid.UUID, designation_id: uuid.UUID) -> DesignationItemResponse:
        """Get designation with organization ownership check."""
        res = await self.session.execute(
            select(Designation).where(Designation.id == designation_id, Designation.company_id == company_id)
        )
        d = res.scalar_one_or_none()
        if not d:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")
        return DesignationItemResponse(
            id=str(d.id),
            company_id=str(d.company_id),
            name=d.name,
            description=d.description,
            created_at=d.created_at.isoformat() if d.created_at else None,
        )

    async def update_designation(
        self, company_id: uuid.UUID, designation_id: uuid.UUID, payload: DesignationUpdateInput
    ) -> DesignationItemResponse:
        """Update designation."""
        res = await self.session.execute(
            select(Designation).where(Designation.id == designation_id, Designation.company_id == company_id)
        )
        d = res.scalar_one_or_none()
        if not d:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")

        if payload.name:
            clean = payload.name.strip()
            dup = await self.session.execute(
                select(Designation).where(
                    Designation.company_id == company_id,
                    Designation.id != designation_id,
                    func.lower(Designation.name) == clean.lower()
                )
            )
            if dup.scalars().first():
                raise ConflictException(message=f"Designation '{clean}' already exists in this organization.")
            d.name = clean

        if payload.description is not None:
            d.description = payload.description

        await self.session.commit()
        return await self.get_designation(company_id, designation_id)

    async def delete_designation(self, company_id: uuid.UUID, designation_id: uuid.UUID) -> bool:
        """Delete designation."""
        res = await self.session.execute(
            select(Designation).where(Designation.id == designation_id, Designation.company_id == company_id)
        )
        d = res.scalar_one_or_none()
        if not d:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")

        await self.session.delete(d)
        await self.session.commit()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 4: Work Schedule & HR Settings
    # ─────────────────────────────────────────────────────────────────────────

    async def get_work_schedule(self, company_id: uuid.UUID) -> WorkScheduleResponse:
        """Get Work Schedule and HR Settings."""
        res = await self.session.execute(
            select(CompanySettings).where(CompanySettings.company_id == company_id)
        )
        cs = res.scalar_one_or_none()

        shift_res = await self.session.execute(
            select(Shift).where(Shift.company_id == company_id)
        )
        sh = shift_res.scalars().first()

        start_time = "09:00"
        end_time = "18:00"
        if cs and cs.office_timing and " - " in cs.office_timing:
            parts = cs.office_timing.split(" - ")
            start_time = parts[0].strip()
            end_time = parts[1].strip()
        elif sh:
            start_time = sh.start_time
            end_time = sh.end_time

        working_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        if cs and cs.working_days and isinstance(cs.working_days, dict) and "days" in cs.working_days:
            working_days = cs.working_days["days"]

        return WorkScheduleResponse(
            timezone=cs.timezone if cs and cs.timezone else "Asia/Kolkata",
            currency=cs.currency if cs and cs.currency else "INR",
            date_format=cs.date_format if cs and cs.date_format else "YYYY-MM-DD",
            time_format=cs.time_format if cs and cs.time_format else "12h",
            financial_year=cs.financial_year if cs and cs.financial_year else "2026-2027",
            week_start_day=cs.week_start_day if cs and cs.week_start_day else "Monday",
            working_days=working_days,
            office_start_time=start_time,
            office_end_time=end_time,
            default_shift=cs.default_shift if cs and cs.default_shift else "General Shift",
        )

    async def update_work_schedule(self, company_id: uuid.UUID, payload: WorkScheduleInput) -> WorkScheduleResponse:
        """Persist Work Schedule and HR Settings in database."""
        res = await self.session.execute(
            select(CompanySettings).where(CompanySettings.company_id == company_id)
        )
        cs = res.scalar_one_or_none()

        office_timing = f"{payload.office_start_time} - {payload.office_end_time}"

        if not cs:
            cs = CompanySettings(
                id=uuid.uuid4(),
                company_id=company_id,
                timezone=payload.timezone,
                currency=payload.currency,
                date_format=payload.date_format,
                time_format=payload.time_format,
                financial_year=payload.financial_year,
                week_start_day=payload.week_start_day,
                working_days={"days": payload.working_days},
                office_timing=office_timing,
                default_shift=payload.default_shift,
                leave_policy_template="Standard Template",
            )
            self.session.add(cs)
        else:
            cs.timezone = payload.timezone
            cs.currency = payload.currency
            cs.date_format = payload.date_format
            cs.time_format = payload.time_format
            cs.financial_year = payload.financial_year
            cs.week_start_day = payload.week_start_day
            cs.working_days = {"days": payload.working_days}
            cs.office_timing = office_timing
            cs.default_shift = payload.default_shift

        # Synchronize default Shift record
        shift_res = await self.session.execute(
            select(Shift).where(Shift.company_id == company_id)
        )
        sh = shift_res.scalars().first()
        if not sh:
            sh = Shift(
                id=uuid.uuid4(),
                company_id=company_id,
                name=payload.default_shift,
                start_time=payload.office_start_time,
                end_time=payload.office_end_time,
            )
            self.session.add(sh)
        else:
            sh.name = payload.default_shift
            sh.start_time = payload.office_start_time
            sh.end_time = payload.office_end_time

        # Update JSON on company for cached retrieval
        company = await self.get_company(company_id)
        company.hr_settings = payload.model_dump()
        flag_modified(company, "hr_settings")

        progress = await self.get_or_create_progress(company_id)
        progress.hr_completed = True
        await self._sync_completed_steps(progress)

        await self.session.commit()
        return await self.get_work_schedule(company_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 4: Leave Policies CRUD (Annual, Sick, Casual, etc.)
    # ─────────────────────────────────────────────────────────────────────────

    async def create_leave_policy(self, company_id: uuid.UUID, payload: LeavePolicyCreateInput) -> LeavePolicyResponse:
        """Create a leave policy with organization isolation."""
        clean_name = payload.name.strip()
        dup = await self.session.execute(
            select(LeavePolicy).where(
                LeavePolicy.company_id == company_id,
                func.lower(LeavePolicy.name) == clean_name.lower()
            )
        )
        if dup.scalars().first():
            raise ConflictException(message=f"Leave policy '{clean_name}' already exists in this organization.")

        policy = LeavePolicy(
            id=uuid.uuid4(),
            company_id=company_id,
            name=clean_name,
            leave_type=(payload.leave_type or "ANNUAL").upper(),
            days_allowed=float(payload.days_allowed),
            description=payload.description or f"{clean_name} allocation",
            status=payload.status or "ACTIVE",
        )
        self.session.add(policy)
        await self.session.commit()

        return LeavePolicyResponse(
            id=str(policy.id),
            company_id=str(policy.company_id),
            name=policy.name,
            leave_type=policy.leave_type or "ANNUAL",
            days_allowed=float(policy.days_allowed),
            description=policy.description,
            status=policy.status or "ACTIVE",
            created_at=policy.created_at.isoformat() if policy.created_at else None,
        )

    async def list_leave_policies(self, company_id: uuid.UUID) -> List[LeavePolicyResponse]:
        """List leave policies for organization."""
        res = await self.session.execute(
            select(LeavePolicy).where(LeavePolicy.company_id == company_id).order_by(LeavePolicy.name)
        )
        return [
            LeavePolicyResponse(
                id=str(p.id),
                company_id=str(p.company_id),
                name=p.name,
                leave_type=p.leave_type or "ANNUAL",
                days_allowed=float(p.days_allowed),
                description=p.description,
                status=p.status or "ACTIVE",
                created_at=p.created_at.isoformat() if p.created_at else None,
            )
            for p in res.scalars().all()
        ]

    async def get_leave_policy(self, company_id: uuid.UUID, policy_id: uuid.UUID) -> LeavePolicyResponse:
        """Get leave policy by ID."""
        res = await self.session.execute(
            select(LeavePolicy).where(LeavePolicy.id == policy_id, LeavePolicy.company_id == company_id)
        )
        p = res.scalar_one_or_none()
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")
        return LeavePolicyResponse(
            id=str(p.id),
            company_id=str(p.company_id),
            name=p.name,
            leave_type=p.leave_type or "ANNUAL",
            days_allowed=float(p.days_allowed),
            description=p.description,
            status=p.status or "ACTIVE",
            created_at=p.created_at.isoformat() if p.created_at else None,
        )

    async def update_leave_policy(
        self, company_id: uuid.UUID, policy_id: uuid.UUID, payload: LeavePolicyUpdateInput
    ) -> LeavePolicyResponse:
        """Update leave policy."""
        res = await self.session.execute(
            select(LeavePolicy).where(LeavePolicy.id == policy_id, LeavePolicy.company_id == company_id)
        )
        p = res.scalar_one_or_none()
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")

        if payload.name:
            clean = payload.name.strip()
            dup = await self.session.execute(
                select(LeavePolicy).where(
                    LeavePolicy.company_id == company_id,
                    LeavePolicy.id != policy_id,
                    func.lower(LeavePolicy.name) == clean.lower()
                )
            )
            if dup.scalars().first():
                raise ConflictException(message=f"Leave policy '{clean}' already exists in this organization.")
            p.name = clean

        if payload.leave_type:
            p.leave_type = payload.leave_type.upper()
        if payload.days_allowed is not None:
            p.days_allowed = float(payload.days_allowed)
        if payload.description is not None:
            p.description = payload.description
        if payload.status:
            p.status = payload.status

        await self.session.commit()
        return await self.get_leave_policy(company_id, policy_id)

    async def delete_leave_policy(self, company_id: uuid.UUID, policy_id: uuid.UUID) -> bool:
        """Delete leave policy."""
        res = await self.session.execute(
            select(LeavePolicy).where(LeavePolicy.id == policy_id, LeavePolicy.company_id == company_id)
        )
        p = res.scalar_one_or_none()
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")

        await self.session.delete(p)
        await self.session.commit()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 5: Individual Employee Invitations (STRICTLY NO BULK)
    # ─────────────────────────────────────────────────────────────────────────

    async def send_individual_invitation(
        self, company_id: uuid.UUID, user_id: uuid.UUID, payload: IndividualInvitationInput
    ) -> InvitationResponse:
        """Send individual employee invitation. Bulk APIs are strictly prohibited."""
        clean_email = str(payload.employee_email).lower().strip()
        clean_name = payload.employee_name.strip()

        # Duplicate check: check if an active pending invitation exists
        active_dup = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company_id,
                func.lower(EmployeeInvitation.email) == clean_email,
                EmployeeInvitation.status == "PENDING"
            )
        )
        if active_dup.scalars().first():
            raise ConflictException(
                message=f"An active pending invitation already exists for '{clean_email}' in this organization."
            )

        # Generate cryptographically secure token & 7-day expiry
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        invitation = EmployeeInvitation(
            id=uuid.uuid4(),
            company_id=company_id,
            invited_by=user_id,
            employee_name=clean_name,
            email=clean_email,
            department=payload.department,
            designation=payload.designation,
            token=token,
            status="PENDING",
            expires_at=expires_at,
        )
        self.session.add(invitation)

        # Also create or sync invited Employee record in draft/invited state
        emp_res = await self.session.execute(
            select(Employee).where(
                Employee.company_id == company_id,
                func.lower(Employee.personal_email) == clean_email
            )
        )
        emp = emp_res.scalars().first()
        if not emp:
            name_parts = clean_name.split(" ", 1)
            emp = Employee(
                id=uuid.uuid4(),
                company_id=company_id,
                employee_id=f"EMP-INV-{secrets.token_hex(3).upper()}",
                first_name=name_parts[0],
                last_name=name_parts[1] if len(name_parts) > 1 else "",
                personal_email=clean_email,
                company_email=clean_email,
                department=payload.department or "General",
                designation=payload.designation or "Employee",
                status="INVITED",
                activation_token=token,
                activation_token_expires_at=expires_at,
                invited_at=datetime.now(timezone.utc),
                invited_by=user_id,
                created_by=user_id,
            )
            self.session.add(emp)
        else:
            emp.status = "INVITED"
            emp.activation_token = token
            emp.activation_token_expires_at = expires_at
            emp.invited_at = datetime.now(timezone.utc)
            emp.invited_by = user_id

        progress = await self.get_or_create_progress(company_id, user_id)
        progress.employees_invited = True
        await self._sync_completed_steps(progress)

        await self.session.commit()

        logger.info("Sent employee invitation: email=%s | company_id=%s", clean_email, company_id)

        return InvitationResponse(
            id=str(invitation.id),
            company_id=str(invitation.company_id),
            employee_name=invitation.employee_name,
            employee_email=invitation.email,
            department=invitation.department,
            designation=invitation.designation,
            invitation_token=invitation.token,
            status=invitation.status,
            expires_at=invitation.expires_at.isoformat(),
            created_at=invitation.created_at.isoformat(),
        )

    async def list_pending_invitations(self, company_id: uuid.UUID) -> List[InvitationResponse]:
        """List all pending invitations for this organization."""
        res = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company_id,
                EmployeeInvitation.status == "PENDING"
            ).order_by(EmployeeInvitation.created_at.desc())
        )
        return [
            InvitationResponse(
                id=str(i.id),
                company_id=str(i.company_id),
                employee_name=i.employee_name,
                employee_email=i.email,
                department=i.department,
                designation=i.designation,
                invitation_token=i.token,
                status=i.status,
                expires_at=i.expires_at.isoformat(),
                created_at=i.created_at.isoformat(),
            )
            for i in res.scalars().all()
        ]

    async def resend_invitation(self, company_id: uuid.UUID, invitation_id: uuid.UUID) -> InvitationResponse:
        """Resend invitation with refreshed token and extended 7-day expiry."""
        res = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.id == invitation_id,
                EmployeeInvitation.company_id == company_id
            )
        )
        inv = res.scalar_one_or_none()
        if not inv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")

        new_token = secrets.token_urlsafe(32)
        new_expiry = datetime.now(timezone.utc) + timedelta(days=7)

        inv.token = new_token
        inv.expires_at = new_expiry
        inv.status = "PENDING"

        # Update linked employee record
        emp_res = await self.session.execute(
            select(Employee).where(
                Employee.company_id == company_id,
                func.lower(Employee.personal_email) == inv.email.lower()
            )
        )
        emp = emp_res.scalars().first()
        if emp:
            emp.activation_token = new_token
            emp.activation_token_expires_at = new_expiry
            emp.status = "INVITED"

        await self.session.commit()
        logger.info("Resent invitation: id=%s | email=%s", invitation_id, inv.email)

        return InvitationResponse(
            id=str(inv.id),
            company_id=str(inv.company_id),
            employee_name=inv.employee_name,
            employee_email=inv.email,
            department=inv.department,
            designation=inv.designation,
            invitation_token=inv.token,
            status=inv.status,
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat(),
        )

    async def cancel_invitation(self, company_id: uuid.UUID, invitation_id: uuid.UUID) -> bool:
        """Cancel a pending invitation."""
        res = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.id == invitation_id,
                EmployeeInvitation.company_id == company_id
            )
        )
        inv = res.scalar_one_or_none()
        if not inv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")

        inv.status = "CANCELLED"

        # Clear token on employee
        emp_res = await self.session.execute(
            select(Employee).where(
                Employee.company_id == company_id,
                func.lower(Employee.personal_email) == inv.email.lower()
            )
        )
        emp = emp_res.scalars().first()
        if emp and emp.status == "INVITED":
            emp.activation_token = None
            emp.status = "CANCELLED"

        await self.session.commit()
        logger.info("Cancelled invitation: id=%s", invitation_id)
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 6: Review & Complete Onboarding
    # ─────────────────────────────────────────────────────────────────────────

    async def get_organization_structure(self, company_id: uuid.UUID, user_id: uuid.UUID) -> OnboardingReviewResponse:
        """Aggregate full organization structure for the Review & Activate screen."""
        org = await self.get_organization(company_id)
        admin = await self.get_admin_profile(user_id, company_id)
        depts = await self.list_departments(company_id)
        desigs = await self.list_designations(company_id)
        sched = await self.get_work_schedule(company_id)
        leaves = await self.list_leave_policies(company_id)
        invites = await self.list_pending_invitations(company_id)
        progress = await self.get_or_create_progress(company_id, user_id)

        status_resp = self._build_status_response(progress)

        return OnboardingReviewResponse(
            organization=org.model_dump(),
            admin_profile=admin.model_dump(),
            departments=[d.model_dump() for d in depts],
            designations=[d.model_dump() for d in desigs],
            work_schedule=sched.model_dump(),
            leave_policies=[l.model_dump() for l in leaves],
            pending_invitations=[i.model_dump() for i in invites],
            onboarding_status=status_resp.status,
            current_step=status_resp.current_step,
            completion_percentage=status_resp.completion_percentage,
        )

    async def complete_onboarding(self, company_id: uuid.UUID, user_id: uuid.UUID) -> Dict[str, Any]:
        """Transactional, idempotent completion of HR Admin onboarding."""
        company = await self.get_company(company_id)
        user = await self.get_user(user_id)
        progress = await self.get_or_create_progress(company_id, user_id)

        # Idempotency check: if already completed, return immediately without duplicating records
        if progress.onboarding_completed and company.onboarding_completed:
            logger.info("complete_onboarding called on already completed organization: %s", company_id)
            return {
                "completed": True,
                "onboarding_completed": True,
                "status": "completed",
                "organization_status": "ACTIVE",
                "completed_at": progress.completed_at.isoformat() if progress.completed_at else datetime.now(timezone.utc).isoformat(),
                "message": "Onboarding has already been completed.",
            }

        # Validate required data before activation
        depts_count = await self.session.scalar(
            select(func.count(Department.id)).where(Department.company_id == company_id, Department.is_deleted.is_(False))
        )
        if not depts_count or depts_count == 0:
            # Create a default department if none existed
            default_dept = Department(
                id=uuid.uuid4(),
                company_id=company_id,
                department_name="General Management",
                department_code="MGMT",
                description="Executive and General Administration",
                location="Headquarters",
                status="ACTIVE",
                created_by=user_id,
            )
            self.session.add(default_dept)

        desigs_count = await self.session.scalar(
            select(func.count(Designation.id)).where(Designation.company_id == company_id)
        )
        if not desigs_count or desigs_count == 0:
            self.session.add(Designation(
                id=uuid.uuid4(),
                company_id=company_id,
                name="HR Administrator",
                description="Human Resources Administrator",
            ))

        # Seed default CompanySettings if missing
        cs_res = await self.session.execute(select(CompanySettings).where(CompanySettings.company_id == company_id))
        if not cs_res.scalar_one_or_none():
            self.session.add(CompanySettings(
                id=uuid.uuid4(),
                company_id=company_id,
                timezone="Asia/Kolkata",
                currency="INR",
                date_format="YYYY-MM-DD",
                time_format="12h",
                financial_year="2026-2027",
                week_start_day="Monday",
                working_days={"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
                office_timing="09:00 - 18:00",
                default_shift="General Shift",
                leave_policy_template="Standard Template",
            ))

        # Seed default Shift if missing
        sh_res = await self.session.execute(select(Shift).where(Shift.company_id == company_id))
        if not sh_res.scalar_one_or_none():
            self.session.add(Shift(
                id=uuid.uuid4(),
                company_id=company_id,
                name="General Shift",
                start_time="09:00",
                end_time="18:00",
            ))

        # Seed default Leave Policies if missing
        lp_res = await self.session.execute(select(LeavePolicy).where(LeavePolicy.company_id == company_id))
        if not lp_res.scalars().all():
            for name, ltype, days, desc in [
                ("Annual Leave", "ANNUAL", 18.0, "Standard Annual Paid Leave"),
                ("Sick Leave", "SICK", 12.0, "Medical and Sick Leave"),
                ("Casual Leave", "CASUAL", 12.0, "Casual Leave allocation"),
            ]:
                self.session.add(LeavePolicy(
                    id=uuid.uuid4(),
                    company_id=company_id,
                    name=name,
                    leave_type=ltype,
                    days_allowed=days,
                    description=desc,
                    status="ACTIVE",
                ))

        now = datetime.now(timezone.utc)

        # Activate organization
        company.onboarding_completed = True
        company.onboarding_step = 6
        setattr(company, "status", "ACTIVE")

        prof = company.company_profile or {}
        prof["completed"] = True
        prof["completed_at"] = now.isoformat()
        company.company_profile = prof
        flag_modified(company, "company_profile")

        # Activate HR Admin user
        user.onboarding_completed = True
        user.onboarding_step = 6

        # Activate progress state
        progress.company_completed = True
        progress.admin_completed = True
        progress.hr_completed = True
        progress.departments_completed = True
        progress.designations_completed = True
        progress.employees_invited = True
        progress.onboarding_completed = True
        progress.current_step = 6
        progress.status = "completed"
        progress.completed_at = now
        await self._sync_completed_steps(progress)

        await self.session.commit()
        logger.info("HR Admin Onboarding COMPLETED & ACTIVATED: company_id=%s | admin_id=%s", company_id, user_id)

        return {
            "completed": True,
            "onboarding_completed": True,
            "status": "completed",
            "organization_status": "ACTIVE",
            "completed_at": now.isoformat(),
            "message": "Organization onboarding completed and workspace activated successfully.",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Progress Persistence Helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def get_or_create_progress(
        self, company_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> OnboardingProgress:
        """Fetch or create persistent OnboardingProgress row."""
        res = await self.session.execute(
            select(OnboardingProgress).where(OnboardingProgress.company_id == company_id)
        )
        progress = res.scalar_one_or_none()

        if not progress:
            progress = OnboardingProgress(
                id=uuid.uuid4(),
                company_id=company_id,
                user_id=user_id,
                current_step=1,
                status="not_started",
                completed_steps=[],
                started_at=datetime.now(timezone.utc),
            )
            self.session.add(progress)
            await self.session.flush()

        if user_id and not progress.user_id:
            progress.user_id = user_id

        return progress

    async def save_progress(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        current_step: int,
        completed_steps: list[int | str] | None = None,
        status_val: str | None = None,
    ) -> OnboardingProgressResponse:
        """Save onboarding progress from step wizard."""
        progress = await self.get_or_create_progress(company_id, user_id)

        progress.current_step = current_step
        if completed_steps is not None:
            progress.completed_steps = completed_steps
        if status_val:
            progress.status = status_val
        elif progress.status == "not_started":
            progress.status = "in_progress"

        await self.session.commit()
        return await self.get_progress_response(company_id, user_id)

    async def get_progress_response(self, company_id: uuid.UUID, user_id: uuid.UUID) -> OnboardingProgressResponse:
        """Get all saved progress and wizard data."""
        company = await self.get_company(company_id)
        progress = await self.get_or_create_progress(company_id, user_id)

        admin = await self.get_admin_profile(user_id, company_id)
        depts = await self.list_departments(company_id)
        desigs = await self.list_designations(company_id)
        sched = await self.get_work_schedule(company_id)
        leaves = await self.list_leave_policies(company_id)
        invites = await self.list_pending_invitations(company_id)

        return OnboardingProgressResponse(
            onboarding_completed=bool(progress.onboarding_completed or company.onboarding_completed),
            current_step=progress.current_step,
            status=progress.status or "in_progress",
            started_at=progress.started_at.isoformat() if progress.started_at else None,
            completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
            last_updated_at=progress.updated_at.isoformat() if progress.updated_at else None,
            company_profile=company.company_profile,
            hr_settings=sched.model_dump(),
            admin_profile=admin.model_dump(),
            departments=[d.model_dump() for d in depts],
            designations=[d.model_dump() for d in desigs],
            shifts=[{"name": sched.default_shift, "start_time": sched.office_start_time, "end_time": sched.office_end_time}],
            leave_policies=[l.model_dump() for l in leaves],
            pending_invitations=[i.model_dump() for i in invites],
            step_flags={
                "admin_completed": progress.admin_completed,
                "company_completed": progress.company_completed,
                "departments_completed": progress.departments_completed,
                "designations_completed": progress.designations_completed,
                "hr_completed": progress.hr_completed,
                "employees_invited": progress.employees_invited,
                "onboarding_completed": progress.onboarding_completed,
            },
        )

    def _build_status_response(self, progress: OnboardingProgress) -> OnboardingStatusResponse:
        total_steps = 6
        completed_count = sum([
            progress.admin_completed,
            progress.company_completed,
            progress.departments_completed,
            progress.designations_completed,
            progress.hr_completed,
            progress.employees_invited,
        ])
        pct = 100.0 if progress.onboarding_completed else round((completed_count / total_steps) * 100.0, 2)

        return OnboardingStatusResponse(
            onboarding_completed=bool(progress.onboarding_completed),
            current_step=progress.current_step,
            completion_percentage=pct,
            status=progress.status or ("completed" if progress.onboarding_completed else "in_progress"),
            started_at=progress.started_at.isoformat() if progress.started_at else None,
            completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
            last_updated_at=progress.updated_at.isoformat() if progress.updated_at else None,
            company_completed=progress.company_completed,
            admin_completed=progress.admin_completed,
            hr_completed=progress.hr_completed,
            departments_completed=progress.departments_completed,
            designations_completed=progress.designations_completed,
            employees_invited=progress.employees_invited,
        )

    async def _sync_completed_steps(self, progress: OnboardingProgress) -> None:
        steps = []
        if progress.admin_completed:
            steps.append(1)
        if progress.company_completed:
            steps.append(2)
        if progress.departments_completed and progress.designations_completed:
            steps.append(3)
        if progress.hr_completed:
            steps.append(4)
        if progress.employees_invited:
            steps.append(5)
        if progress.onboarding_completed:
            steps.append(6)
        progress.completed_steps = steps
