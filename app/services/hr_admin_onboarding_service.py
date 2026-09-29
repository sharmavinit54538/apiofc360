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
import hashlib
import html
import logging
import secrets
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_invitation import EmployeeInvitation
from app.models.onboarding import CompanySettings, Designation, LeavePolicy, OnboardingProgress, Shift
from app.models.user import User
from app.core.config import settings
from app.services.email_service import send_email
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
    OrganizationStructureInput,
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

    # The current step is *derived* from persisted completion evidence.  It is
    # never accepted from a browser request.  The flag names are legacy column
    # names, while this is the canonical product ordering:
    # 1 Company, 2 Admin profile, 3 HR settings, 4 Org structure,
    # 5 Invitations/skip, 6 Review, 7 Completed.
    _REQUIRED_BEFORE = {
        1: (),
        2: ("company_completed",),
        3: ("company_completed", "admin_completed"),
        4: ("company_completed", "admin_completed", "hr_completed"),
        5: ("company_completed", "admin_completed", "hr_completed", "departments_completed", "designations_completed"),
        6: ("company_completed", "admin_completed", "hr_completed", "departments_completed", "designations_completed", "employees_invited"),
    }

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(value.split()).casefold()

    async def _require_prior_steps(self, progress: OnboardingProgress, target_step: int) -> None:
        missing = [flag for flag in self._REQUIRED_BEFORE[target_step] if not getattr(progress, flag)]
        if missing:
            await self._refresh_state(progress)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Complete the preceding onboarding step before saving step {target_step}.",
            )

    async def _refresh_state(self, progress: OnboardingProgress, company: Company | None = None) -> None:
        """Recompute state from backend facts without ever regressing completed work."""
        if progress.onboarding_completed:
            progress.current_step = 7
            progress.status = "completed"
        elif not progress.company_completed:
            progress.current_step = 1
            progress.status = "not_started"
        elif not progress.admin_completed:
            progress.current_step = 2
            progress.status = "in_progress"
        elif not progress.hr_completed:
            progress.current_step = 3
            progress.status = "in_progress"
        elif not (progress.departments_completed and progress.designations_completed):
            progress.current_step = 4
            progress.status = "in_progress"
        elif not progress.employees_invited:
            progress.current_step = 5
            progress.status = "in_progress"
        else:
            progress.current_step = 6
            progress.status = "in_progress"

        await self._sync_completed_steps(progress)
        if company is not None:
            company.onboarding_step = progress.current_step
            company.onboarding_completed = bool(progress.onboarding_completed)

    @staticmethod
    def _invitation_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def _refresh_organization_completion(self, progress: OnboardingProgress, company: Company | None = None) -> None:
        """Step 4 is complete only when both persisted collections are non-empty."""
        department_count = await self.session.scalar(
            select(func.count(Department.id)).where(
                Department.company_id == progress.company_id,
                Department.is_deleted.is_(False),
            )
        )
        designation_count = await self.session.scalar(
            select(func.count(Designation.id)).where(Designation.company_id == progress.company_id)
        )
        progress.departments_completed = bool(department_count)
        progress.designations_completed = bool(designation_count)
        await self._refresh_state(progress, company)

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

        progress = await self.get_or_create_progress(company_id, user_id)
        # A completed profile may always be revisited, but first completion
        # cannot bypass the company stage.
        if not progress.admin_completed:
            await self._require_prior_steps(progress, 2)

        if payload.work_email and payload.work_email.lower().strip() != (user.email or "").lower().strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="work_email must match the authenticated account email. Change account email through the verified email workflow.",
            )

        clean_first = payload.first_name.strip()
        clean_last = payload.last_name.strip()
        clean_phone = payload.phone_number.strip()
        user.name = f"{clean_first} {clean_last}".strip()
        user.phone = clean_phone

        # A registered HR Admin is already represented by User.  Update an
        # existing linked Employee profile if one exists, but never manufacture
        # an employee with placeholder department/designation values here.
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

        progress.admin_completed = True
        await self._refresh_state(progress, company)

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
        canonical_name = company.name or prof.get("company_name") or prof.get("name") or "Organization"

        org_data = {
            "id": str(company.id),
            "name": canonical_name,
            "company_name": canonical_name,
            "legal_name": prof.get("legal_name"),
            "industry": prof.get("industry"),
            "company_size": prof.get("company_size") or prof.get("companySize"),
            "website": prof.get("website"),
            "country": prof.get("country", "India"),
            "address": prof.get("address"),
            "city": prof.get("city"),
            "state": prof.get("state"),
            "zip_code": prof.get("zip_code") or prof.get("zipCode"),
            "cin": prof.get("cin"),
            "gst_number": prof.get("gst_number") or prof.get("gstNumber"),
            "company_logo_url": prof.get("company_logo_url") or prof.get("company_logo") or prof.get("logo"),
            "company_stamp_url": prof.get("company_stamp_url") or prof.get("company_stamp") or prof.get("stamp"),
            "timezone": company.timezone or prof.get("timezone"),
            "currency": prof.get("currency"),
            "status": getattr(company, "status", "PENDING") or "PENDING",
            "onboarding_completed": bool(company.onboarding_completed),
        }

        return OrganizationResponse(
            **org_data,
            organization=org_data,
        )

    async def create_organization(self, user_id: uuid.UUID, payload: OrganizationInput) -> OrganizationResponse:
        """Create a new organization for the HR Admin."""
        user = await self.get_user(user_id)
        clean_name = payload.company_name.strip() if payload.company_name else ""
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="company_name is required when creating an organization.",
            )

        # If user already has a company, update it instead of creating duplicates
        if user.company_id:
            existing = await self.get_company(user.company_id)
            if existing:
                return await self.update_organization(user.company_id, payload)

        company = Company(
            id=uuid.uuid4(),
            name=clean_name,
            onboarding_completed=False,
            onboarding_step=1,
            company_profile=payload.model_dump(),
        )
        setattr(company, "status", "PENDING")
        self.session.add(company)
        await self.session.flush()

        user.company_id = company.id
        self.session.add(user)

        progress = await self.get_or_create_progress(company.id, user_id)
        progress.company_completed = True
        await self._refresh_state(progress, company)

        await self.session.commit()
        return await self.get_organization(company.id)

    async def update_organization(self, company_id: uuid.UUID, payload: OrganizationInput) -> OrganizationResponse:
        """Update organization details."""
        try:
            company = await self.get_company(company_id)
            if payload.company_name and payload.company_name.strip():
                clean_name = payload.company_name.strip()
                if len(clean_name) > 100:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Company name cannot exceed 100 characters.",
                    )
                company.name = clean_name
            else:
                clean_name = company.name

            if payload.timezone:
                company.timezone = payload.timezone

            prof = company.company_profile or {}
            update_dict = payload.model_dump(exclude_unset=True)
            prof.update(update_dict)
            prof["company_name"] = clean_name
            prof["name"] = clean_name
            prof["companyName"] = clean_name
            company.company_profile = prof
            flag_modified(company, "company_profile")

            progress = await self.get_or_create_progress(company_id)
            progress.company_completed = True
            await self._refresh_state(progress, company)

            # Sync timezone and currency to CompanySettings if provided
            if payload.timezone or payload.currency:
                cs_res = await self.session.execute(
                    select(CompanySettings).where(CompanySettings.company_id == company_id).order_by(CompanySettings.created_at.desc()).limit(1)
                )
                cs = cs_res.scalars().first()
                if cs:
                    if payload.timezone:
                        cs.timezone = payload.timezone
                    if payload.currency:
                        cs.currency = payload.currency
                else:
                    self.session.add(CompanySettings(
                        id=uuid.uuid4(),
                        company_id=company_id,
                        timezone=payload.timezone or "Asia/Kolkata",
                        currency=payload.currency or "INR",
                    ))

            await self.session.commit()
            return await self.get_organization(company_id)
        except HTTPException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.warning("Organization save conflict for company_id=%s", company_id, exc_info=exc)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization data conflicts with an existing record.") from exc
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Failed to update organization %s", company_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to save organization at this time.",
            ) from exc

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3: Departments CRUD (Strictly Isolated, No Demo Records)
    # ─────────────────────────────────────────────────────────────────────────

    async def create_department(
        self, company_id: uuid.UUID, user_id: uuid.UUID, payload: DepartmentCreateInput
    ) -> DepartmentItemResponse:
        """Create department for an organization. Prevents duplicates and demo data."""
        clean_name = payload.department_name.strip()
        clean_code = (payload.department_code or "").strip()
        if not clean_name or not clean_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="department_name and department_code are required.",
            )
        normalized_name = self._normalized(clean_name)
        normalized_code = self._normalized(clean_code)

        progress = await self.get_or_create_progress(company_id, user_id)
        if not progress.departments_completed:
            await self._require_prior_steps(progress, 4)

        # Duplicate check within company
        dup_check = await self.session.execute(
            select(Department).where(
                Department.company_id == company_id,
                (Department.normalized_name == normalized_name) |
                (Department.normalized_code == normalized_code)
            )
        )
        if dup_check.scalars().first():
            raise ConflictException(message=f"Department '{clean_name}' or code '{clean_code}' already exists in this organization.")

        dept = Department(
            id=uuid.uuid4(),
            company_id=company_id,
            department_name=clean_name,
            department_code=clean_code,
            normalized_name=normalized_name,
            normalized_code=normalized_code,
            description=payload.description or "",
            location=payload.location or "Headquarters",
            status="ACTIVE",
            created_by=user_id,
        )
        self.session.add(dept)

        try:
            await self.session.flush()
            await self._refresh_organization_completion(progress, await self.get_company(company_id))
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="A department with this name or code already exists in this organization.") from exc
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
            dept.normalized_name = self._normalized(clean_name)

        if payload.department_code:
            clean_code = payload.department_code.strip()
            if not clean_code:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="department_code cannot be empty.")
            code_dup = await self.session.execute(
                select(Department).where(
                    Department.company_id == company_id,
                    Department.id != department_id,
                    Department.normalized_code == self._normalized(clean_code),
                )
            )
            if code_dup.scalars().first():
                raise ConflictException(message=f"Department code '{clean_code}' already exists in this organization.")
            dept.department_code = clean_code
            dept.normalized_code = self._normalized(clean_code)
        if payload.description is not None:
            dept.description = payload.description
        if payload.location:
            dept.location = payload.location
        if payload.status:
            dept.status = payload.status

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="A department with this name or code already exists in this organization.") from exc
        return await self.get_department(company_id, department_id)

    async def delete_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> bool:
        """Delete department belonging to organization."""
        stmt = select(Department).where(Department.id == department_id, Department.company_id == company_id)
        res = await self.session.execute(stmt)
        dept = res.scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")

        await self.session.delete(dept)
        progress = await self.get_or_create_progress(company_id)
        await self._refresh_organization_completion(progress, await self.get_company(company_id))
        await self.session.commit()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3: Designations CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def create_designation(self, company_id: uuid.UUID, payload: DesignationCreateInput) -> DesignationItemResponse:
        """Create designation for organization with duplicate prevention."""
        clean_name = payload.name.strip()
        if not clean_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Designation name cannot be empty.")
        normalized_name = self._normalized(clean_name)
        progress = await self.get_or_create_progress(company_id)
        if not progress.designations_completed:
            await self._require_prior_steps(progress, 4)
        dup = await self.session.execute(
            select(Designation).where(
                Designation.company_id == company_id,
                Designation.normalized_name == normalized_name
            )
        )
        if dup.scalars().first():
            raise ConflictException(message=f"Designation '{clean_name}' already exists in this organization.")

        desig = Designation(
            id=uuid.uuid4(),
            company_id=company_id,
            name=clean_name,
            normalized_name=normalized_name,
            description=payload.description,
        )
        self.session.add(desig)
        try:
            await self.session.flush()
            await self._refresh_organization_completion(progress, await self.get_company(company_id))
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="A designation with this name already exists in this organization.") from exc
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
            d.normalized_name = self._normalized(clean)

        if payload.description is not None:
            d.description = payload.description

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="A designation with this name already exists in this organization.") from exc
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
        progress = await self.get_or_create_progress(company_id)
        await self._refresh_organization_completion(progress, await self.get_company(company_id))
        await self.session.commit()
        return True

    async def save_organization_structure(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: OrganizationStructureInput,
    ) -> tuple[List[DepartmentItemResponse], List[DesignationItemResponse]]:
        """Save departments and designations in one all-or-nothing transaction.

        Repeating an identical request updates the matching normalized records,
        which makes browser retries idempotent without weakening the database
        uniqueness guarantees.
        """
        progress = await self.get_or_create_progress(company_id, user_id)
        if not (progress.departments_completed and progress.designations_completed):
            await self._require_prior_steps(progress, 4)

        seen_departments: set[tuple[str, str]] = set()
        seen_designations: set[str] = set()
        departments: list[Department] = []
        designations: list[Designation] = []
        try:
            for item in payload.departments:
                name = item.department_name.strip()
                code = (item.department_code or "").strip()
                if not name or not code:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Each department requires a name and code.")
                key = (self._normalized(name), self._normalized(code))
                if key in seen_departments:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Duplicate department in organization request.")
                seen_departments.add(key)
                existing = await self.session.scalar(
                    select(Department).where(
                        Department.company_id == company_id,
                        Department.normalized_name == key[0],
                        Department.is_deleted.is_(False),
                    )
                )
                if existing:
                    if existing.normalized_code != key[1]:
                        raise ConflictException(message=f"Department '{name}' already exists with a different code.")
                    existing.description = item.description or ""
                    existing.location = item.location or "Headquarters"
                    departments.append(existing)
                    continue
                department = Department(
                    id=uuid.uuid4(), company_id=company_id, created_by=user_id,
                    department_name=name, department_code=code,
                    normalized_name=key[0], normalized_code=key[1],
                    description=item.description or "", location=item.location or "Headquarters", status="ACTIVE",
                )
                self.session.add(department)
                departments.append(department)

            for item in payload.designations:
                name = item.name.strip()
                normalized = self._normalized(name)
                if normalized in seen_designations:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Duplicate designation in organization request.")
                seen_designations.add(normalized)
                existing = await self.session.scalar(
                    select(Designation).where(
                        Designation.company_id == company_id,
                        Designation.normalized_name == normalized,
                    )
                )
                if existing:
                    existing.description = item.description
                    designations.append(existing)
                    continue
                designation = Designation(
                    id=uuid.uuid4(), company_id=company_id, name=name,
                    normalized_name=normalized, description=item.description,
                )
                self.session.add(designation)
                designations.append(designation)

            await self.session.flush()
            await self._refresh_organization_completion(progress, await self.get_company(company_id))
            await self.session.commit()
        except HTTPException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="Organization structure conflicts with an existing department or designation.") from exc

        return (
            [
                DepartmentItemResponse(
                    id=str(department.id), company_id=str(department.company_id),
                    department_name=department.department_name, department_code=department.department_code,
                    description=department.description, location=department.location, status=department.status,
                    employee_count=0, created_at=department.created_at.isoformat() if department.created_at else None,
                )
                for department in departments
            ],
            [
                DesignationItemResponse(
                    id=str(designation.id), company_id=str(designation.company_id), name=designation.name,
                    description=designation.description,
                    created_at=designation.created_at.isoformat() if designation.created_at else None,
                )
                for designation in designations
            ],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 4: Work Schedule & HR Settings
    # ─────────────────────────────────────────────────────────────────────────

    async def get_work_schedule(self, company_id: uuid.UUID) -> WorkScheduleResponse:
        """Get Work Schedule and HR Settings."""
        res = await self.session.execute(
            select(CompanySettings).where(CompanySettings.company_id == company_id).order_by(CompanySettings.created_at.desc()).limit(1)
        )
        cs = res.scalars().first()

        shift_res = await self.session.execute(
            select(Shift).where(Shift.company_id == company_id)
        )
        sh = shift_res.scalars().first()

        start_time = "09:00"
        end_time = "18:00"
        if cs and cs.office_start_time and cs.office_end_time:
            start_time = cs.office_start_time
            end_time = cs.office_end_time
        elif cs and cs.office_timing and " - " in cs.office_timing:
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
            leave_policy_template=cs.leave_policy_template if cs else None,
        )

    async def update_work_schedule(self, company_id: uuid.UUID, payload: WorkScheduleInput) -> WorkScheduleResponse:
        """Persist Work Schedule and HR Settings in database."""
        res = await self.session.execute(
            select(CompanySettings).where(CompanySettings.company_id == company_id).order_by(CompanySettings.created_at.desc()).limit(1)
        )
        cs = res.scalars().first()
        progress = await self.get_or_create_progress(company_id)
        if not progress.hr_completed:
            await self._require_prior_steps(progress, 3)

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
                office_start_time=payload.office_start_time,
                office_end_time=payload.office_end_time,
                default_shift=payload.default_shift,
                leave_policy_template=payload.leave_policy_template,
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
            cs.office_start_time = payload.office_start_time
            cs.office_end_time = payload.office_end_time
            cs.default_shift = payload.default_shift
            cs.leave_policy_template = payload.leave_policy_template

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

        progress.hr_completed = True
        await self._refresh_state(progress, company)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="HR settings could not be saved due to a concurrent update.") from exc
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
        """Create a durable invitation, then record the real delivery result.

        The database commit happens before SMTP.  If SMTP fails the invitation
        remains retryable with ``delivery_status=FAILED`` rather than claiming
        it was sent.  This method intentionally does not invent an Employee
        record from a name and email; the normal employee module owns employee
        creation after acceptance.
        """
        clean_email = str(payload.employee_email).lower().strip()
        clean_name = payload.employee_name.strip()

        progress = await self.get_or_create_progress(company_id, user_id)
        if not progress.employees_invited:
            await self._require_prior_steps(progress, 5)

        now = datetime.now(timezone.utc)
        await self.session.execute(
            text("UPDATE employee_invitations SET status = 'EXPIRED' WHERE company_id = :company_id AND status = 'PENDING' AND expires_at <= :now"),
            {"company_id": company_id, "now": now},
        )

        # Duplicate check: check if an active pending invitation exists
        active_dup = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company_id,
                func.lower(EmployeeInvitation.email) == clean_email,
                EmployeeInvitation.status == "PENDING",
                EmployeeInvitation.expires_at > now,
            )
        )
        if active_dup.scalars().first():
            raise ConflictException(
                message=f"An active pending invitation already exists for '{clean_email}' in this organization."
            )

        # The token is only available to the email delivery routine.  Persist
        # a SHA-256 digest in both legacy ``token`` and ``token_hash`` columns
        # so neither database reads nor list APIs can recover the secret.
        token = secrets.token_urlsafe(32)
        token_hash = self._invitation_token_hash(token)
        expires_at = now + timedelta(days=7)

        invitation = EmployeeInvitation(
            id=uuid.uuid4(),
            company_id=company_id,
            invited_by=user_id,
            employee_name=clean_name,
            email=clean_email,
            department=payload.department,
            designation=payload.designation,
            token=token_hash,
            token_hash=token_hash,
            status="PENDING",
            delivery_status="QUEUED",
            expires_at=expires_at,
        )
        self.session.add(invitation)
        progress.employees_invited = True
        data = dict(progress.data or {})
        data["invitations_skipped"] = False
        progress.data = data
        await self._refresh_state(progress, await self.get_company(company_id))
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(message="An active invitation already exists for this email address.") from exc

        await self._deliver_invitation(invitation, token)
        logger.info("onboarding_invitation_created company_id=%s invitation_id=%s", company_id, invitation.id)
        return self._invitation_response(invitation)

    def _invitation_response(self, invitation: EmployeeInvitation) -> InvitationResponse:
        return InvitationResponse(
            id=str(invitation.id), company_id=str(invitation.company_id),
            employee_name=invitation.employee_name, employee_email=invitation.email,
            department=invitation.department, designation=invitation.designation,
            status=invitation.status, delivery_status=invitation.delivery_status,
            expires_at=invitation.expires_at.isoformat(),
            created_at=invitation.created_at.isoformat(),
        )

    async def _deliver_invitation(self, invitation: EmployeeInvitation, raw_token: str) -> None:
        company = await self.get_company(invitation.company_id)
        activation_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/onboarding/accept?token={raw_token}"
        safe_name = html.escape(invitation.employee_name)
        safe_company = html.escape(company.name)
        message = (
            f"<p>Hello {safe_name},</p><p>You have been invited to join {safe_company} on OFC360.</p>"
            f"<p><a href=\"{html.escape(activation_url, quote=True)}\">Accept invitation</a></p>"
            f"<p>This invitation expires on {invitation.expires_at.isoformat()}.</p>"
        )
        try:
            await send_email(invitation.email, f"Invitation to join {company.name} on OFC360", message)
        except Exception as exc:
            invitation.delivery_status = "FAILED"
            invitation.delivery_error = type(exc).__name__
            await self.session.commit()
            logger.warning("onboarding_invitation_failed company_id=%s invitation_id=%s", invitation.company_id, invitation.id)
            return
        invitation.delivery_status = "SENT"
        invitation.delivery_error = None
        invitation.last_sent_at = datetime.now(timezone.utc)
        await self.session.commit()
        logger.info("onboarding_invitation_sent company_id=%s invitation_id=%s", invitation.company_id, invitation.id)

    async def list_pending_invitations(self, company_id: uuid.UUID) -> List[InvitationResponse]:
        """List all pending invitations for this organization."""
        res = await self.session.execute(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company_id,
                EmployeeInvitation.status == "PENDING"
            ).order_by(EmployeeInvitation.created_at.desc())
        )
        return [self._invitation_response(invitation) for invitation in res.scalars().all()]

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

        if inv.status != "PENDING":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending invitations can be resent.")
        new_token = secrets.token_urlsafe(32)
        new_expiry = datetime.now(timezone.utc) + timedelta(days=7)

        token_hash = self._invitation_token_hash(new_token)
        inv.token = token_hash
        inv.token_hash = token_hash
        inv.expires_at = new_expiry
        inv.delivery_status = "QUEUED"
        inv.delivery_error = None
        await self.session.commit()
        await self._deliver_invitation(inv, new_token)
        return self._invitation_response(inv)

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
        inv.token = self._invitation_token_hash(secrets.token_urlsafe(32))
        inv.token_hash = inv.token
        await self.session.commit()
        logger.info("onboarding_invitation_cancelled company_id=%s invitation_id=%s", company_id, invitation_id)
        return True

    async def skip_invitations(self, company_id: uuid.UUID, user_id: uuid.UUID) -> OnboardingProgressResponse:
        """Record a deliberate skip without creating an invitation or sending mail."""
        progress = await self.get_or_create_progress(company_id, user_id)
        if not progress.employees_invited:
            await self._require_prior_steps(progress, 5)
        progress.employees_invited = True
        data = dict(progress.data or {})
        data["invitations_skipped"] = True
        progress.data = data
        await self._refresh_state(progress, await self.get_company(company_id))
        await self.session.commit()
        logger.info("onboarding_invitations_skipped company_id=%s user_id=%s", company_id, user_id)
        return await self.get_progress_response(company_id, user_id)

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
        company = await self.get_company(company_id)
        await self._refresh_organization_completion(progress, company)
        status_resp = self._build_status_response(progress, company=company)

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
            can_activate=(not progress.onboarding_completed and progress.current_step == 6),
        )

    async def complete_onboarding(self, company_id: uuid.UUID, user_id: uuid.UUID) -> Dict[str, Any]:
        """Transactional, idempotent completion of HR Admin onboarding."""
        company = await self.get_company(company_id)
        user = await self.get_user(user_id)
        if user.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot activate another organization.")
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

        await self._refresh_organization_completion(progress, company)
        required_flags = (
            "company_completed", "admin_completed", "hr_completed",
            "departments_completed", "designations_completed", "employees_invited",
        )
        missing = [flag for flag in required_flags if not getattr(progress, flag)]
        if missing:
            await self._refresh_state(progress, company)
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="All required onboarding steps must be completed before workspace activation.",
            )

        now = datetime.now(timezone.utc)

        # Activate organization
        company.onboarding_completed = True
        company.onboarding_step = 7
        setattr(company, "status", "ACTIVE")

        prof = company.company_profile or {}
        prof["completed"] = True
        prof["completed_at"] = now.isoformat()
        company.company_profile = prof
        flag_modified(company, "company_profile")

        # Activate HR Admin user
        user.onboarding_completed = True
        user.onboarding_step = 7

        # Activate progress state
        progress.onboarding_completed = True
        progress.completed_at = now
        await self._refresh_state(progress, company)

        try:
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.exception("workspace_activation_failed company_id=%s", company_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Workspace activation could not be completed.") from exc
        logger.info("workspace_activated company_id=%s admin_id=%s", company_id, user_id)

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
            # A unique database constraint protects the row.  A savepoint
            # lets concurrent first requests recover without rolling back the
            # caller's whole onboarding transaction.
            try:
                async with self.session.begin_nested():
                    progress = OnboardingProgress(
                        id=uuid.uuid4(), company_id=company_id, user_id=user_id,
                        current_step=1, status="not_started", completed_steps=[],
                        started_at=datetime.now(timezone.utc),
                    )
                    self.session.add(progress)
                    await self.session.flush()
            except IntegrityError:
                res = await self.session.execute(
                    select(OnboardingProgress).where(OnboardingProgress.company_id == company_id)
                )
                progress = res.scalar_one()

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
        """Reject legacy client-controlled progress writes.

        Keeping this service entry point prevents accidental reintroduction of
        a second implementation, while making the previous unsafe contract
        fail loudly rather than silently discarding a frontend value.
        """
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding progress is calculated by the server from completed onboarding data.",
        )

    async def get_progress_response(self, company_id: uuid.UUID, user_id: uuid.UUID) -> OnboardingProgressResponse:
        """Get all saved progress and wizard data."""
        company = await self.get_company(company_id)
        progress = await self.get_or_create_progress(company_id, user_id)
        await self._refresh_state(progress, company)

        admin = await self.get_admin_profile(user_id, company_id)
        depts = await self.list_departments(company_id)
        desigs = await self.list_designations(company_id)
        sched = await self.get_work_schedule(company_id)
        leaves = await self.list_leave_policies(company_id)
        invites = await self.list_pending_invitations(company_id)

        # Merge authoritative company name from companies.name into response representation without mutating DB JSONB
        raw_profile = dict(company.company_profile or {})
        canonical_name = company.name or raw_profile.get("company_name") or raw_profile.get("name") or "Organization"
        raw_profile["name"] = canonical_name
        raw_profile["company_name"] = canonical_name
        raw_profile["companyName"] = canonical_name

        org_summary = {
            "id": str(company.id),
            "name": canonical_name,
            "company_name": canonical_name,
        }

        return OnboardingProgressResponse(
            company_id=str(company.id),
            organization=org_summary,
            onboarding_completed=bool(progress.onboarding_completed or company.onboarding_completed),
            current_step=progress.current_step,
            status=progress.status or "in_progress",
            started_at=progress.started_at.isoformat() if progress.started_at else None,
            completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
            last_updated_at=progress.updated_at.isoformat() if progress.updated_at else None,
            company_profile=raw_profile,
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

    def _build_status_response(
        self,
        progress: OnboardingProgress,
        company: Company | None = None,
    ) -> OnboardingStatusResponse:
        total_steps = 6
        completed_count = sum([
            progress.company_completed,
            progress.admin_completed,
            progress.hr_completed,
            bool(progress.departments_completed and progress.designations_completed),
            progress.employees_invited,
        ])
        pct = 100.0 if progress.onboarding_completed else round((completed_count / total_steps) * 100.0, 2)

        org_summary = None
        if company:
            canonical_name = company.name or (company.company_profile or {}).get("company_name") or "Organization"
            org_summary = {
                "id": str(company.id),
                "name": canonical_name,
                "company_name": canonical_name,
            }

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
            organization=org_summary,
        )

    async def _sync_completed_steps(self, progress: OnboardingProgress) -> None:
        steps = []
        if progress.company_completed:
            steps.append(1)
        if progress.admin_completed:
            steps.append(2)
        if progress.hr_completed:
            steps.append(3)
        if progress.departments_completed and progress.designations_completed:
            steps.append(4)
        if progress.employees_invited:
            steps.append(5)
        if progress.onboarding_completed:
            steps.extend([6, 7])
        progress.completed_steps = steps
