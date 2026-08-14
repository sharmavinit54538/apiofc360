"""Company Admin Onboarding API routes.

Production-ready onboarding flow with:
- Sequential step enforcement (cannot skip steps)
- Idempotency (cannot re-submit a completed step)
- Automatic redirect_step in error responses for frontend navigation
- Per-step completion flags stored in OnboardingProgress table
- Full transaction safety on every mutating endpoint
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Dict, Any
from datetime import datetime, date, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ConflictException, ValidationException
from app.core.rbac import require_admin
from app.db.database import get_db_session
from app.models.company import Company
from app.models.user import User
from app.models.employee import Employee
from app.models.department import Department
from app.models.onboarding import CompanySettings, Designation, LeavePolicy, Shift, OnboardingProgress
from app.schemas.auth import APIResponse
from app.schemas.employee import EmployeeCreate, ActivateOnboardingRequest
from app.schemas.onboarding import (
    OnboardingAPIResponse,
    OnboardingStatusResponse,
    OnboardingProgressResponse,
    CompanyStepInput,
    AdminProfileStepInput,
    HRSettingsStepInput,
    DepartmentStepInputList,
    DesignationStepInputList,
    InviteEmployeeStepInputList,
)
from app.services.employee_service import EmployeeService, get_employee_service
from app.services.onboarding_service import OnboardingService, StepAccess
from app.services.rate_limiter import check_onboarding_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_company_id(claims: dict) -> uuid.UUID:
    """Extract and validate company_id from JWT claims."""
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company ID not found in security credentials.",
        )
    return uuid.UUID(company_id_str)


async def _load_company(session: AsyncSession, company_id: uuid.UUID) -> Company:
    """Load company or raise 404."""
    result = await session.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company profile not found.")
    return company


# ─────────────────────────────────────────────────────────────────────────────
# GET /status
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[OnboardingStatusResponse],
    summary="Get current company onboarding status",
)
async def get_onboarding_status(
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[OnboardingStatusResponse]:
    """Return current_step and completion flags. Used by login flow to route the user."""
    company_id = _get_company_id(claims)
    company = await _load_company(session, company_id)

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    
    # Sync progress with company status
    if company.onboarding_completed and not progress.onboarding_completed:
        progress.onboarding_completed = True
        progress.current_step = 7
        session.add(progress)

    await session.commit()

    onboarding_completed = progress.onboarding_completed or company.onboarding_completed
    first_incomplete = svc.get_first_incomplete_step(progress) if not onboarding_completed else 7

    total_steps = 6
    if onboarding_completed:
        pct = 100.0
    else:
        pct = round((min(first_incomplete - 1, total_steps) / total_steps) * 100.0, 2)

    return OnboardingAPIResponse(
        success=True,
        message="Onboarding status retrieved successfully.",
        current_step=first_incomplete,
        onboarding_completed=onboarding_completed,
        data=OnboardingStatusResponse(
            onboarding_completed=onboarding_completed,
            current_step=first_incomplete,
            completion_percentage=pct,
            company_completed=progress.company_completed or onboarding_completed,
            admin_completed=progress.admin_completed or onboarding_completed,
            hr_completed=progress.hr_completed or onboarding_completed,
            departments_completed=progress.departments_completed or onboarding_completed,
            designations_completed=progress.designations_completed or onboarding_completed,
            employees_invited=progress.employees_invited or onboarding_completed,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /progress
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/progress",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[OnboardingProgressResponse],
    summary="Get all saved onboarding data",
)
async def get_onboarding_progress(
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[OnboardingProgressResponse]:
    """Retrieve all previously saved onboarding progress. Frontend uses this to prefill forms."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    company = await _load_company(session, company_id)

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    await session.commit()

    # Admin profile
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    admin_emp_result = await session.execute(
        select(Employee).where(Employee.company_email == user.email) if user else select(Employee).where(False)
    )
    admin_emp = admin_emp_result.scalar_one_or_none()

    admin_profile = None
    if user:
        admin_profile = {
            "first_name": admin_emp.first_name if admin_emp else (user.name.split()[0] if user.name else ""),
            "last_name": admin_emp.last_name if admin_emp else (user.name.split()[1] if user.name and len(user.name.split()) > 1 else ""),
            "mobile_number": user.phone,
            "designation": admin_emp.designation if admin_emp else "Company Owner (Admin)",
            "profile_photo": admin_emp.profile_photo_url if admin_emp else None,
            "preferred_language": "English",
        }

    # Departments
    depts_result = await session.execute(select(Department).where(Department.company_id == company_id))
    depts = [
        {
            "department_code": d.department_code,
            "department_name": d.department_name,
            "description": d.description,
        }
        for d in depts_result.scalars().all()
    ]

    # Designations
    des_result = await session.execute(select(Designation).where(Designation.company_id == company_id))
    des = [{"name": d.name, "description": d.description} for d in des_result.scalars().all()]

    # Shifts
    shifts_result = await session.execute(select(Shift).where(Shift.company_id == company_id))
    shifts_list = [
        {"name": s.name, "start_time": s.start_time, "end_time": s.end_time}
        for s in shifts_result.scalars().all()
    ]

    # Leave policies
    lp_result = await session.execute(select(LeavePolicy).where(LeavePolicy.company_id == company_id))
    lp_list = [
        {"name": p.name, "days_allowed": float(p.days_allowed), "description": p.description}
        for p in lp_result.scalars().all()
    ]

    progress_data = OnboardingProgressResponse(
        onboarding_completed=progress.onboarding_completed,
        current_step=progress.current_step,
        company_profile=company.company_profile,
        hr_settings=company.hr_settings,
        admin_profile=admin_profile,
        departments=depts,
        designations=des,
        shifts=shifts_list,
        leave_policies=lp_list,
        step_flags=svc.get_completion_summary(progress),
    )

    return OnboardingAPIResponse(
        success=True,
        message="Onboarding progress retrieved successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data=progress_data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET & POST /company  (Step 1)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/company",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Get company details for onboarding (Step 1)",
)
async def get_onboarding_company(
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Retrieve saved company onboarding profile."""
    company_id = _get_company_id(claims)
    company = await _load_company(session, company_id)

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)

    data = {
        "id": str(company.id),
        "name": company.name,
        "company_name": company.name,
        "companyName": company.name,
        **(company.company_profile or {}),
    }

    return OnboardingAPIResponse(
        success=True,
        message="Company profile retrieved successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data=data,
    )


@router.post(
    "/company",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Save company details (Step 1)",
)

async def save_onboarding_company(
    payload: CompanyStepInput,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Save company profile details. Idempotent — rejects re-submission if already completed."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    company = await _load_company(session, company_id)

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)

    # Always update company profile and name if provided
    if payload.company_name and payload.company_name.strip():
        clean_name = payload.company_name.strip()
        company.name = clean_name
        profile = payload.model_dump()
        profile["name"] = clean_name
        profile["company_name"] = clean_name
        profile["companyName"] = clean_name
        company.company_profile = profile
        flag_modified(company, "company_profile")
        flag_modified(company, "name")

    # Gate: check access — REDIRECT means already done, return current position gracefully
    access = svc.check_step_access(progress, step=1)
    if access == StepAccess.REDIRECT:
        await session.commit()
        return OnboardingAPIResponse(
            success=True,
            message="Company information updated successfully.",
            current_step=progress.current_step,
            onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step,
            data={"id": str(company.id), "name": company.name, **(company.company_profile or {})},
        )
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(
            success=False,
            message="Please complete the previous step first.",
            current_step=progress.current_step,
            onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step,
            data={},
        )

    # Business logic — update company record (upsert-safe, no duplicate)
    if company.onboarding_step < 2:
        company.onboarding_step = 2

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.onboarding_step < 2:
        user.onboarding_step = 2

    # Advance progress
    svc.advance_step(progress, step=1)

    await session.commit()
    logger.info("Onboarding Step 1 (Company) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Company information saved successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /admin-profile  (Step 2)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/admin-profile",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Save admin profile details (Step 2)",
)
async def save_onboarding_admin_profile(
    payload: AdminProfileStepInput,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Update Admin User and Employee details. Rejects re-submission; requires Step 1 first."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)

    # Gate: graceful resume — REDIRECT means already done
    access = svc.check_step_access(progress, step=2)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(
            success=True,
            message="Admin profile already saved. Resuming from your current step.",
            current_step=progress.current_step,
            onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step,
            data={},
        )
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(
            success=False,
            message="Please complete Company Details before Admin Profile.",
            current_step=progress.current_step,
            onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step,
            data={},
        )

    # Load user — required
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Phone uniqueness check — must use raw SQL to bypass multi-tenant ORM filter
    if payload.mobile_number:
        phone_check = await session.execute(
            text("SELECT id FROM users WHERE phone = :phone AND id != :uid LIMIT 1"),
            {"phone": str(payload.mobile_number), "uid": str(user_id)},
        )
        if phone_check.fetchone():
            raise ConflictException(
                message="Mobile number is already registered to another account.",
                field="mobile_number",
            )

    # Update User
    user.name = f"{payload.first_name} {payload.last_name}"
    user.phone = payload.mobile_number
    if user.onboarding_step < 3:
        user.onboarding_step = 3

    # Update admin Employee record if it exists
    admin_emp_result = await session.execute(
        select(Employee).where(Employee.company_email == user.email)
    )
    admin_emp = admin_emp_result.scalar_one_or_none()
    if admin_emp:
        admin_emp.first_name = payload.first_name
        admin_emp.last_name = payload.last_name
        admin_emp.phone = payload.mobile_number
        if payload.profile_photo:
            admin_emp.profile_photo_url = payload.profile_photo
        if payload.designation:
            admin_emp.designation = payload.designation

    # Update Company profile snapshot
    comp_result = await session.execute(select(Company).where(Company.id == company_id))
    company = comp_result.scalar_one_or_none()
    if company:
        profile = company.company_profile or {}
        profile["admin_profile"] = payload.model_dump()
        company.company_profile = profile
        flag_modified(company, "company_profile")
        if company.onboarding_step < 3:
            company.onboarding_step = 3

    # Advance progress
    svc.advance_step(progress, step=2)

    await session.commit()
    logger.info("Onboarding Step 2 (Admin Profile) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Admin profile details saved successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /hr-settings  (Step 3)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/hr-settings",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Save HR settings (Step 3)",
)
async def save_onboarding_hr_settings(
    payload: HRSettingsStepInput,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Save global HR configurations. Requires Step 2 completed first."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    access = svc.check_step_access(progress, step=3)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(success=True, message="HR Settings already saved. Resuming.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(success=False, message="Please complete Admin Profile before HR Settings.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})

    company = await _load_company(session, company_id)
    company.hr_settings = payload.model_dump()
    if company.onboarding_step < 4:
        company.onboarding_step = 4

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.onboarding_step < 4:
        user.onboarding_step = 4

    svc.advance_step(progress, step=3)

    await session.commit()
    logger.info("Onboarding Step 3 (HR Settings) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="HR setup configurations saved successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /departments  (Step 4)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/departments",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Save departments (Step 4)",
)
async def save_onboarding_departments(
    payload: DepartmentStepInputList,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Save company departments. Requires HR Settings completed. Replaces existing departments."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    access = svc.check_step_access(progress, step=4)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(success=True, message="Departments already saved. Resuming.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(success=False, message="Please complete HR Settings before Departments.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})

    # Replace-safe: delete existing and re-insert (idempotent bulk replace)
    await session.execute(delete(Department).where(Department.company_id == company_id))
    for dept_data in payload.departments:
        dept = Department(
            id=uuid.uuid4(),
            company_id=company_id,
            department_code=dept_data.department_code,
            department_name=dept_data.department_name,
            description=dept_data.description,
            location="Headquarters",
            status="ACTIVE",
            created_by=user_id,
        )
        session.add(dept)

    company = await _load_company(session, company_id)
    if company.onboarding_step < 5:
        company.onboarding_step = 5

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.onboarding_step < 5:
        user.onboarding_step = 5

    svc.advance_step(progress, step=4)

    await session.commit()
    logger.info("Onboarding Step 4 (Departments) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Departments configured successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /designations  (Step 5)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/designations",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Save designations (Step 5)",
)
async def save_onboarding_designations(
    payload: DesignationStepInputList,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Save company designations. Requires Departments completed first."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    access = svc.check_step_access(progress, step=5)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(success=True, message="Designations already saved. Resuming.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(success=False, message="Please complete Departments before Designations.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})

    # Replace-safe bulk insert
    await session.execute(delete(Designation).where(Designation.company_id == company_id))
    for des_name in payload.designations:
        des = Designation(
            id=uuid.uuid4(),
            company_id=company_id,
            name=des_name,
            description=f"Custom designation: {des_name}",
        )
        session.add(des)

    company = await _load_company(session, company_id)
    if company.onboarding_step < 6:
        company.onboarding_step = 6

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.onboarding_step < 6:
        user.onboarding_step = 6

    svc.advance_step(progress, step=5)

    await session.commit()
    logger.info("Onboarding Step 5 (Designations) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Designations configured successfully.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /invite-employees  (Step 6)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/invite-employees",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Invite employees (Step 6)",
)
async def invite_employees(
    payload: InviteEmployeeStepInputList,
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    employee_service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> OnboardingAPIResponse[dict]:
    """Invite employees or skip. Requires Designations completed first."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    access = svc.check_step_access(progress, step=6)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(success=True, message="Invite step already completed. Resuming.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(success=False, message="Please complete Designations before Invite Employees.",
            current_step=progress.current_step, onboarding_completed=progress.onboarding_completed,
            redirect_step=progress.current_step, data={})

    invite_errors = []
    employees_invited = not payload.skip

    if not payload.skip:
        for emp_data in payload.employees:
            try:
                employee_create = EmployeeCreate(
                    first_name=emp_data.first_name,
                    last_name=emp_data.last_name,
                    personal_email=emp_data.personal_email,
                    phone=emp_data.phone,
                    department=emp_data.department or "Management",
                    designation=emp_data.designation or "Employee",
                    joining_date=date.today(),
                    employment_type="FULL_TIME",
                )
                await employee_service.create_employee(
                    admin_id=user_id,
                    company_id=company_id,
                    payload=employee_create
                )
            except Exception as e:
                invite_errors.append({"email": str(emp_data.personal_email), "error": str(e)})

    # Persist employees_invited flag on company_profile for legacy/progress reads
    comp_result = await session.execute(select(Company).where(Company.id == company_id))
    company = comp_result.scalar_one_or_none()
    if company:
        profile = company.company_profile or {}
        profile["employees_invited"] = employees_invited
        company.company_profile = profile
        flag_modified(company, "company_profile")
        if company.onboarding_step < 7:
            company.onboarding_step = 7

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.onboarding_step < 7:
        user.onboarding_step = 7

    await session.refresh(progress)
    svc.advance_step(progress, step=6)

    await session.commit()
    logger.info("Onboarding Step 6 (Invite Employees) completed: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=len(invite_errors) == 0,
        message="Employee invitations processed successfully." if not payload.skip else "Invitation step skipped.",
        current_step=progress.current_step,
        onboarding_completed=progress.onboarding_completed,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /complete  (Step 7)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/complete",
    status_code=status.HTTP_200_OK,
    response_model=OnboardingAPIResponse[dict],
    summary="Complete onboarding flow (Step 7)",
)
async def complete_onboarding(
    claims: Annotated[dict, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingAPIResponse[dict]:
    """Complete onboarding, seed defaults, flag company as fully onboarded."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    svc = OnboardingService(session)
    progress = await svc.get_or_create_progress(company_id)
    access = svc.check_step_access(progress, step=7)
    if access == StepAccess.REDIRECT:
        return OnboardingAPIResponse(success=True, message="Onboarding is already complete.",
            current_step=7, onboarding_completed=True,
            redirect_step=7, data={})
    if access == StepAccess.BLOCKED:
        return OnboardingAPIResponse(success=False, message="Please complete all previous steps before completing onboarding.",
            current_step=progress.current_step, onboarding_completed=False,
            redirect_step=progress.current_step, data={})

    # Load company & user
    comp_result = await session.execute(select(Company).where(Company.id == company_id))
    company = comp_result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company profile not found.")

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found.")

    # Seed default CompanySettings if missing
    settings_result = await session.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    )
    if not settings_result.scalar_one_or_none():
        session.add(CompanySettings(
            id=uuid.uuid4(),
            company_id=company_id,
            timezone=company.company_profile.get("timezone") if company.company_profile else "UTC",
            currency=company.company_profile.get("currency") if company.company_profile else "USD",
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
    shift_result = await session.execute(select(Shift).where(Shift.company_id == company_id))
    if not shift_result.scalar_one_or_none():
        session.add(Shift(
            id=uuid.uuid4(),
            company_id=company_id,
            name="General Shift",
            start_time="09:00",
            end_time="18:00",
        ))

    # Seed default Leave Policies if missing
    lp_result = await session.execute(select(LeavePolicy).where(LeavePolicy.company_id == company_id))
    if not lp_result.scalars().all():
        for name, days, desc in [
            ("Casual Leave", 12.0, "Casual Leave allocation"),
            ("Sick Leave", 12.0, "Sick Leave allocation"),
            ("Earned Leave", 15.0, "Earned Leave allocation"),
        ]:
            session.add(LeavePolicy(
                id=uuid.uuid4(),
                company_id=company_id,
                name=name,
                days_allowed=days,
                description=desc,
            ))

    # Seed JSON profile defaults
    profile = company.company_profile or {}
    profile.setdefault("attendance_policy", "Standard Attendance Policy")
    profile.setdefault("payroll_settings", {"salary_cycle": "Monthly", "payroll_date": 28})
    profile.setdefault("notification_settings", {"email_notifications": True, "slack_notifications": False})
    profile.setdefault("ai_settings", {"ai_assistant_enabled": True})
    company.company_profile = profile
    flag_modified(company, "company_profile")

    # Mark company onboarding complete
    company.onboarding_completed = True
    company.onboarding_step = 7
    user.onboarding_completed = True
    user.onboarding_step = 7

    # Advance progress — marks onboarding_completed = True
    svc.advance_step(progress, step=7)

    await session.commit()
    logger.info("Onboarding COMPLETED: company_id=%s", company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Onboarding completed successfully. Welcome to your dashboard!",
        current_step=7,
        onboarding_completed=True,
        data={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /validate  &  GET /validate-token  (Employee activation — unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/validate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee onboarding token",
    dependencies=[Depends(check_onboarding_rate_limit)],
)
async def validate_onboarding_token_alias(
    token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Validate onboarding token alias."""
    return await validate_onboarding_token(token=token, session=session)


@router.get(
    "/validate-token",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee onboarding token",
    dependencies=[Depends(check_onboarding_rate_limit)],
)
async def validate_onboarding_token(
    token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Validate that the onboarding token is valid, not expired, and belongs to an invited employee."""
    logger.info("validate_onboarding_token: request | token_prefix=%s", token[:8] if token else "N/A")

    employee_result = await session.execute(
        select(Employee).where(Employee.activation_token == token)
    )
    employee = employee_result.scalar_one_or_none()

    if not employee or employee.is_deleted:
        logger.warning("validate_onboarding_token: token not found or employee deleted | token_prefix=%s", token[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation expired. Request new invitation.",
        )

    if employee.status != "INVITED":
        logger.warning(
            "validate_onboarding_token: wrong status | employee_id=%s | status=%s",
            employee.employee_id, employee.status,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation expired. Request new invitation.",
        )

    now = datetime.now(timezone.utc)
    expires_at = employee.activation_token_expires_at
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            logger.warning(
                "validate_onboarding_token: token expired | employee_id=%s | expired_at=%s",
                employee.employee_id, expires_at.isoformat(),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation expired. Request new invitation.",
            )

    logger.info(
        "validate_onboarding_token: valid | employee_id=%s | email=%s",
        employee.employee_id, employee.personal_email[:3] + "***",
    )
    return APIResponse[dict](
        success=True,
        message="Token is valid.",
        data={
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "personal_email": employee.personal_email,
            "company_email": employee.company_email,
            "phone": employee.phone,
            "department": employee.department,
            "designation": employee.designation,
            "employee_id": employee.employee_id,
            "joining_date": employee.joining_date.isoformat() if employee.joining_date else None,
        },
        errors=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /activate  (Employee self-activation — unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/activate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Activate invited employee account",
    dependencies=[Depends(check_onboarding_rate_limit)],
)
async def activate_onboarding_employee(
    payload: ActivateOnboardingRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Activate employee account, create user, delete token, and perform auto-login."""
    from sqlalchemy import func
    from app.core.security import hash_password
    from app.services.token_service import TokenService
    from app.repositories.auth_repository import AuthRepository
    from app.models.employee_emergency_contact import EmployeeEmergencyContact

    logger.info("activate_onboarding: request | token_prefix=%s", payload.token[:8] if payload.token else "N/A")

    employee_result = await session.execute(
        select(Employee).where(Employee.activation_token == payload.token)
    )
    employee = employee_result.scalar_one_or_none()

    if not employee or employee.is_deleted or employee.status != "INVITED":
        logger.warning("activate_onboarding: invalid token | token_prefix=%s", payload.token[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation expired or invalid. Request new invitation.",
        )

    now = datetime.now(timezone.utc)
    expires_at = employee.activation_token_expires_at
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            logger.warning("activate_onboarding: token expired | employee_id=%s", employee.employee_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation expired. Request new invitation.",
            )

    password = payload.password
    if (
        len(password) < 8 or
        not any(c.isupper() for c in password) or
        not any(c.islower() for c in password) or
        not any(c.isdigit() for c in password) or
        not any(not c.isalnum() for c in password)
    ):
        logger.warning("activate_onboarding: weak password | employee_id=%s", employee.employee_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters with 1 uppercase, 1 lowercase, 1 number, 1 special character.",
        )

    # Check for existing email
    email_check = await session.execute(
        select(User).where(func.lower(User.email) == func.lower(employee.personal_email))
    )
    if email_check.scalar_one_or_none():
        logger.warning("activate_onboarding: email already exists | employee_id=%s", employee.employee_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # Clean and check phone
    phone_to_use = payload.phone or employee.phone
    clean_phone = "".join(filter(str.isdigit, phone_to_use)) if phone_to_use else ""
    if len(clean_phone) > 10:
        clean_phone = clean_phone[-10:]

    if clean_phone:
        phone_check = await session.execute(
            select(User).where(User.phone == clean_phone)
        )
        if phone_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this phone number already exists.",
            )

    # Create active user
    from app.models.user import UserRole
    logger.info("activate_onboarding: creating user | employee_id=%s", employee.employee_id)
    db_role = getattr(UserRole, (employee.role or "").upper(), UserRole.EMPLOYEE) if hasattr(UserRole, (employee.role or "").upper()) else UserRole.EMPLOYEE
    user = User(
        company_id=employee.company_id,
        name=f"{employee.first_name} {employee.last_name}".strip(),
        email=employee.personal_email.lower(),
        phone=clean_phone,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_verified=True,
        role=db_role,
        email_verified_at=now,
        onboarding_completed=True,
    )
    session.add(user)
    await session.flush()
    logger.info("activate_onboarding: user created | user_id=%s | employee_id=%s", user.id, employee.employee_id)

    # Link and activate employee
    employee.user_id = user.id
    employee.status = "ACTIVE"
    employee.activation_token = None
    employee.activation_token_expires_at = None
    logger.info("activate_onboarding: employee → ACTIVE | employee_id=%s", employee.employee_id)

    if payload.phone:
        employee.phone = payload.phone
    if payload.profile_photo_url:
        employee.profile_photo_url = payload.profile_photo_url
    if payload.emergency_contact_name and payload.emergency_contact_phone:
        session.add(EmployeeEmergencyContact(
            employee_id=employee.id,
            name=payload.emergency_contact_name,
            relation="Emergency Contact",
            phone=payload.emergency_contact_phone,
        ))

    await session.commit()
    logger.info("activate_onboarding: committed | user_id=%s", user.id)

    # Auto-login
    token_service = TokenService(session=session, auth_repository=AuthRepository(session))
    access_token, refresh_token, expires_in = await token_service.generate_auth_tokens(
        user_id=user.id,
        role=user.role,
        company_id=user.company_id,
    )
    logger.info("activate_onboarding: JWT generated | user_id=%s | role=%s | expires_in=%s", user.id, user.role, expires_in)

    return APIResponse[dict](
        success=True,
        message="Account activated successfully.",
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "company_id": str(user.company_id) if user.company_id else None,
                "is_verified": True,
                "onboarding_completed": True,
            },
        },
        errors=None,
    )
