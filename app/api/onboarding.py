"""Company Admin & HR Admin Onboarding API routes.

Production-ready onboarding flow with:
- All 6 stages supported: Admin Profile, Company Setup, Departments & Designations CRUD,
  Work Schedule & Leave Policies CRUD, Individual Employee Invitations, Review & Complete
- Multi-tenant isolation and HR Admin role enforcement (403 Forbidden for employees)
- Transaction-safe database persistence with zero mock data
- Token validation & activation endpoints for invited employees
"""

from __future__ import annotations

from datetime import datetime, date, timezone
import logging
import os
import re
import secrets
from typing import Annotated, Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import AppException, ConflictException, NotFoundException, ValidationException
from app.core.rbac import require_hr_admin
from app.db.database import get_db_session
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_invitation import EmployeeInvitation
from app.models.onboarding import CompanySettings, Designation, LeavePolicy, OnboardingProgress, Shift
from app.models.user import User
from app.schemas.auth import APIResponse
from app.schemas.employee import ActivateOnboardingRequest, EmployeeCreate
from app.schemas.onboarding import (
    DepartmentCreateInput,
    DepartmentItemResponse,
    DepartmentStepInputList,
    DepartmentUpdateInput,
    DesignationCreateInput,
    DesignationItemResponse,
    DesignationStepInputList,
    DesignationUpdateInput,
    FileUploadResponse,
    HRAdminProfileInput,
    HRAdminProfileResponse,
    IndividualInvitationInput,
    InvitationListResponse,
    InvitationResponse,
    InviteEmployeeStepInputList,
    LeavePolicyCreateInput,
    LeavePolicyResponse,
    LeavePolicyUpdateInput,
    OnboardingAPIResponse,
    OnboardingProgressResponse,
    OnboardingProgressUpdateInput,
    OnboardingReviewResponse,
    OnboardingStatusResponse,
    OrganizationInput,
    OrganizationResponse,
    WorkScheduleInput,
    WorkScheduleResponse,
)
from app.services.employee_service import (
    EmployeeService,
    get_employee_service,
    mask_token,
    validate_employee_invitation_token,
)
from app.services.hr_admin_onboarding_service import HRAdminOnboardingService
from app.services.rate_limiter import check_onboarding_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# ─────────────────────────────────────────────────────────────────────────────
# Helper: HR Admin Context Resolution
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_admin_context(
    claims: Annotated[dict, Depends(require_hr_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Extract authenticated HR Admin user_id and linked company_id."""
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID missing from credentials.")
    user_id = uuid.UUID(str(user_id_str))

    company_id: uuid.UUID | None = None
    cid_claim = claims.get("company_id")
    if cid_claim and str(cid_claim).lower() not in {"default", "none", ""}:
        try:
            company_id = uuid.UUID(str(cid_claim))
        except (ValueError, TypeError):
            company_id = None

    if not company_id:
        user_res = await session.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if user and user.company_id:
            company_id = user.company_id

    if not company_id:
        # Auto-provision company if none exists
        user_res = await session.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        new_comp = Company(
            id=uuid.uuid4(),
            name=f"{user.name if user and user.name else 'My'} Organization",
            onboarding_completed=False,
            onboarding_step=1,
            company_profile={},
        )
        setattr(new_comp, "status", "PENDING")
        session.add(new_comp)
        await session.flush()
        if user:
            user.company_id = new_comp.id
        company_id = new_comp.id

    return user_id, company_id


# ─────────────────────────────────────────────────────────────────────────────
# 1. Onboarding Status & Progress
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingStatusResponse])
async def get_onboarding_status(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OnboardingStatusResponse]:
    """Get current onboarding status and active step."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    progress = await service.get_or_create_progress(company_id, user_id)
    company = await service.get_company(company_id)
    status_resp = service._build_status_response(progress, company=company)
    return OnboardingAPIResponse(
        success=True,
        message="Onboarding status retrieved successfully.",
        current_step=status_resp.current_step,
        onboarding_completed=status_resp.onboarding_completed,
        data=status_resp,
    )


@router.get("/progress", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingProgressResponse])
async def get_onboarding_progress(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OnboardingProgressResponse]:
    """Retrieve all saved onboarding progress data for form prefill."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    data = await service.get_progress_response(company_id, user_id)
    return OnboardingAPIResponse(
        success=True,
        message="Onboarding progress retrieved successfully.",
        current_step=data.current_step,
        onboarding_completed=data.onboarding_completed,
        data=data,
    )


@router.put("/progress", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingProgressResponse])
@router.patch("/progress", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingProgressResponse])
async def save_onboarding_progress(
    payload: OnboardingProgressUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OnboardingProgressResponse]:
    """Save onboarding step progress in the database."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    data = await service.save_progress(company_id, user_id, payload.current_step, payload.completed_steps, payload.status)
    return OnboardingAPIResponse(
        success=True,
        message="Onboarding progress saved successfully.",
        current_step=data.current_step,
        onboarding_completed=data.onboarding_completed,
        data=data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Stage 1: Admin Profile
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin-profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
@router.get("/profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
async def get_admin_profile(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[HRAdminProfileResponse]:
    """Get HR Admin profile details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    profile = await service.get_admin_profile(user_id, company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Admin profile retrieved successfully.",
        current_step=1,
        onboarding_completed=False,
        data=profile,
    )


@router.post("/admin-profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
@router.put("/admin-profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
@router.post("/profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
@router.put("/profile", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[HRAdminProfileResponse])
async def save_admin_profile(
    payload: HRAdminProfileInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[HRAdminProfileResponse]:
    """Create or update HR Admin profile details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    profile = await service.update_admin_profile(user_id, company_id, payload)
    return OnboardingAPIResponse(
        success=True,
        message="Admin profile saved successfully.",
        current_step=2,
        onboarding_completed=False,
        data=profile,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Stage 2: Company / Organization
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/company", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
@router.get("/organization", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
async def get_company_details(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OrganizationResponse]:
    """Get organization/company details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    org = await service.get_organization(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Company profile retrieved successfully.",
        current_step=2,
        onboarding_completed=org.onboarding_completed,
        data=org,
    )


@router.post("/company", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
@router.put("/company", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
@router.post("/organization", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
@router.put("/organization", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OrganizationResponse])
async def save_company_details(
    payload: OrganizationInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OrganizationResponse]:
    """Create or update company profile details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    org = await service.update_organization(company_id, payload)
    return OnboardingAPIResponse(
        success=True,
        message="Company information saved successfully.",
        current_step=3,
        onboarding_completed=org.onboarding_completed,
        data=org,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stage 3: Departments CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/departments", status_code=status.HTTP_201_CREATED, response_model=OnboardingAPIResponse[Any])
async def create_department_or_list(
    payload: DepartmentCreateInput | DepartmentStepInputList,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Any]:
    """Create a department (or multiple departments via batch payload)."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    if isinstance(payload, DepartmentStepInputList) or hasattr(payload, "departments"):
        # Batch save compatibility
        created_list = []
        for d in payload.departments:
            clean_name = d.department_name.strip()
            clean_code = (d.department_code or "").strip() or None
            inp = DepartmentCreateInput(department_name=clean_name, department_code=clean_code, description=d.description)
            try:
                created = await service.create_department(company_id, user_id, inp)
                created_list.append(created)
            except ConflictException:
                pass  # Idempotent skip of duplicates
        return OnboardingAPIResponse(
            success=True,
            message="Departments configured successfully.",
            current_step=4,
            onboarding_completed=False,
            data={"items": [c.model_dump() for c in created_list]},
        )
    else:
        dept = await service.create_department(company_id, user_id, payload)
        return OnboardingAPIResponse(
            success=True,
            message="Department created successfully.",
            current_step=3,
            onboarding_completed=False,
            data=dept,
        )


@router.get("/departments", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[List[DepartmentItemResponse]])
async def list_departments(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[List[DepartmentItemResponse]]:
    """List departments belonging ONLY to this organization."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    depts = await service.list_departments(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Departments retrieved successfully.",
        current_step=3,
        onboarding_completed=False,
        data=depts,
    )


@router.get("/departments/{department_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DepartmentItemResponse])
async def get_department(
    department_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[DepartmentItemResponse]:
    """Get department details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    dept = await service.get_department(company_id, department_id)
    return OnboardingAPIResponse(success=True, message="Department retrieved.", current_step=3, onboarding_completed=False, data=dept)


@router.put("/departments/{department_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DepartmentItemResponse])
@router.patch("/departments/{department_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DepartmentItemResponse])
async def update_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[DepartmentItemResponse]:
    """Update department."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    dept = await service.update_department(company_id, department_id, payload)
    return OnboardingAPIResponse(success=True, message="Department updated successfully.", current_step=3, onboarding_completed=False, data=dept)


@router.delete("/departments/{department_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def delete_department(
    department_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Delete department."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    await service.delete_department(company_id, department_id)
    return OnboardingAPIResponse(success=True, message="Department deleted successfully.", current_step=3, onboarding_completed=False, data={"id": str(department_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 5. Stage 3: Designations CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/designations", status_code=status.HTTP_201_CREATED, response_model=OnboardingAPIResponse[Any])
async def create_designation_or_list(
    payload: DesignationCreateInput | DesignationStepInputList,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Any]:
    """Create designation(s)."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    if isinstance(payload, DesignationStepInputList) or hasattr(payload, "designations"):
        created = []
        for name in payload.designations:
            clean = name.strip()
            inp = DesignationCreateInput(name=clean)
            try:
                d = await service.create_designation(company_id, inp)
                created.append(d)
            except ConflictException:
                pass
        return OnboardingAPIResponse(
            success=True,
            message="Designations configured successfully.",
            current_step=4,
            onboarding_completed=False,
            data={"items": [c.model_dump() for c in created]},
        )
    else:
        desig = await service.create_designation(company_id, payload)
        return OnboardingAPIResponse(
            success=True,
            message="Designation created successfully.",
            current_step=3,
            onboarding_completed=False,
            data=desig,
        )


@router.get("/designations", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[List[DesignationItemResponse]])
async def list_designations(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[List[DesignationItemResponse]]:
    """List designations belonging to this organization."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    desigs = await service.list_designations(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Designations retrieved successfully.",
        current_step=3,
        onboarding_completed=False,
        data=desigs,
    )


@router.get("/designations/{designation_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DesignationItemResponse])
async def get_designation(
    designation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[DesignationItemResponse]:
    """Get designation details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    desig = await service.get_designation(company_id, designation_id)
    return OnboardingAPIResponse(success=True, message="Designation retrieved.", current_step=3, onboarding_completed=False, data=desig)


@router.put("/designations/{designation_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DesignationItemResponse])
@router.patch("/designations/{designation_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[DesignationItemResponse])
async def update_designation(
    designation_id: uuid.UUID,
    payload: DesignationUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[DesignationItemResponse]:
    """Update designation."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    desig = await service.update_designation(company_id, designation_id, payload)
    return OnboardingAPIResponse(success=True, message="Designation updated successfully.", current_step=3, onboarding_completed=False, data=desig)


@router.delete("/designations/{designation_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def delete_designation(
    designation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Delete designation."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    await service.delete_designation(company_id, designation_id)
    return OnboardingAPIResponse(success=True, message="Designation deleted successfully.", current_step=3, onboarding_completed=False, data={"id": str(designation_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 6. Stage 4: Work Schedule & HR Settings
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/hr-settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.get("/settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.get("/work-schedule", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
async def get_hr_settings(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[WorkScheduleResponse]:
    """Get work schedule and HR settings."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    sched = await service.get_work_schedule(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="HR setup configurations retrieved.",
        current_step=4,
        onboarding_completed=False,
        data=sched,
    )


@router.post("/hr-settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.put("/hr-settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.post("/settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.put("/settings", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.post("/work-schedule", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
@router.put("/work-schedule", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[WorkScheduleResponse])
async def save_hr_settings(
    payload: WorkScheduleInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[WorkScheduleResponse]:
    """Save work schedule and HR settings."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    sched = await service.update_work_schedule(company_id, payload)
    return OnboardingAPIResponse(
        success=True,
        message="HR setup configurations saved successfully.",
        current_step=4,
        onboarding_completed=False,
        data=sched,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Stage 4: Leave Policies CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/leave-policies", status_code=status.HTTP_201_CREATED, response_model=OnboardingAPIResponse[LeavePolicyResponse])
async def create_leave_policy(
    payload: LeavePolicyCreateInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[LeavePolicyResponse]:
    """Create leave policy for organization."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    policy = await service.create_leave_policy(company_id, payload)
    return OnboardingAPIResponse(
        success=True,
        message="Leave policy created successfully.",
        current_step=4,
        onboarding_completed=False,
        data=policy,
    )


@router.get("/leave-policies", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[List[LeavePolicyResponse]])
async def list_leave_policies(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[List[LeavePolicyResponse]]:
    """List leave policies for organization."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    policies = await service.list_leave_policies(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Leave policies retrieved successfully.",
        current_step=4,
        onboarding_completed=False,
        data=policies,
    )


@router.get("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[LeavePolicyResponse])
async def get_leave_policy(
    policy_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[LeavePolicyResponse]:
    """Get leave policy by ID."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    policy = await service.get_leave_policy(company_id, policy_id)
    return OnboardingAPIResponse(success=True, message="Leave policy retrieved.", current_step=4, onboarding_completed=False, data=policy)


@router.put("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[LeavePolicyResponse])
@router.patch("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[LeavePolicyResponse])
async def update_leave_policy(
    policy_id: uuid.UUID,
    payload: LeavePolicyUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[LeavePolicyResponse]:
    """Update leave policy."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    policy = await service.update_leave_policy(company_id, policy_id, payload)
    return OnboardingAPIResponse(success=True, message="Leave policy updated successfully.", current_step=4, onboarding_completed=False, data=policy)


@router.delete("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def delete_leave_policy(
    policy_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Delete leave policy."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    await service.delete_leave_policy(company_id, policy_id)
    return OnboardingAPIResponse(success=True, message="Leave policy deleted successfully.", current_step=4, onboarding_completed=False, data={"id": str(policy_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 8. Stage 5: Individual Employee Invitations (NO BULK IMPORT)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/invitations", status_code=status.HTTP_201_CREATED, response_model=OnboardingAPIResponse[InvitationResponse])
@router.post("/invite-employee", status_code=status.HTTP_201_CREATED, response_model=OnboardingAPIResponse[InvitationResponse])
async def send_individual_invitation(
    payload: IndividualInvitationInput,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[InvitationResponse]:
    """Send an individual employee invitation. Bulk APIs strictly prohibited."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    inv = await service.send_individual_invitation(company_id, user_id, payload)
    return OnboardingAPIResponse(
        success=True,
        message="Employee invitation sent successfully.",
        current_step=5,
        onboarding_completed=False,
        data=inv,
    )


@router.post("/invite-employees", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def invite_employees_batch_step(
    payload: InviteEmployeeStepInputList,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Step 5 compatibility endpoint for wizard form submission."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    invited = []
    if not payload.skip:
        for emp_data in payload.employees:
            name = f"{emp_data.first_name} {emp_data.last_name}".strip()
            inp = IndividualInvitationInput(
                employee_name=name or "Invited Employee",
                employee_email=emp_data.personal_email,
                department=emp_data.department,
                designation=emp_data.designation,
            )
            try:
                inv = await service.send_individual_invitation(company_id, user_id, inp)
                invited.append(inv)
            except ConflictException:
                pass

    return OnboardingAPIResponse(
        success=True,
        message="Employee invitations processed successfully." if not payload.skip else "Invitation step skipped.",
        current_step=6,
        onboarding_completed=False,
        data={"items": [i.model_dump() for i in invited]},
    )


@router.get("/invitations", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[List[InvitationResponse]])
@router.get("/invitations/pending", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[List[InvitationResponse]])
async def list_pending_invitations(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[List[InvitationResponse]]:
    """List pending employee invitations."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    invs = await service.list_pending_invitations(company_id)
    return OnboardingAPIResponse(
        success=True,
        message="Pending invitations retrieved successfully.",
        current_step=5,
        onboarding_completed=False,
        data=invs,
    )


@router.post("/invitations/{invitation_id}/resend", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[InvitationResponse])
async def resend_invitation(
    invitation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[InvitationResponse]:
    """Resend employee invitation."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    inv = await service.resend_invitation(company_id, invitation_id)
    return OnboardingAPIResponse(
        success=True,
        message="Invitation resent successfully.",
        current_step=5,
        onboarding_completed=False,
        data=inv,
    )


@router.post("/invitations/{invitation_id}/cancel", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def cancel_invitation(
    invitation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Cancel employee invitation."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    await service.cancel_invitation(company_id, invitation_id)
    return OnboardingAPIResponse(
        success=True,
        message="Invitation cancelled successfully.",
        current_step=5,
        onboarding_completed=False,
        data={"id": str(invitation_id)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Stage 6: Structure Review & Complete Onboarding
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/structure", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingReviewResponse])
@router.get("/review", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingReviewResponse])
@router.get("/organization/structure", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[OnboardingReviewResponse])
async def get_organization_structure(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[OnboardingReviewResponse]:
    """Return aggregated organization structure for Review screen."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    structure = await service.get_organization_structure(company_id, user_id)
    return OnboardingAPIResponse(
        success=True,
        message="Organization structure retrieved successfully.",
        current_step=6,
        onboarding_completed=False,
        data=structure,
    )


@router.post("/complete", status_code=status.HTTP_200_OK, response_model=OnboardingAPIResponse[Dict[str, Any]])
async def complete_onboarding(
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingAPIResponse[Dict[str, Any]]:
    """Complete HR Admin onboarding, seed required defaults, and activate organization workspace."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    res = await service.complete_onboarding(company_id, user_id)
    return OnboardingAPIResponse(
        success=True,
        message=res["message"],
        current_step=6,
        onboarding_completed=True,
        data=res,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 10. File Upload
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".svg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload", status_code=status.HTTP_200_OK, response_model=APIResponse[FileUploadResponse])
async def upload_onboarding_asset(
    file: UploadFile = File(...),
    category: str = Form(default="company_logo"),
    context: tuple[uuid.UUID, uuid.UUID] = Depends(_resolve_admin_context),
) -> APIResponse[FileUploadResponse]:
    """Upload company logo, company stamp, or admin profile photo with strict validation."""
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content_type = file.content_type or ""
    if content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME content-type '{content_type}'. Must be a valid image.",
        )

    contents = await file.read()
    file_size = len(contents)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds 5MB limit.",
        )
    if file_size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    safe_category = "".join(filter(str.isalnum, category.lower())) or "general"
    upload_dir = os.path.join("uploads", "onboarding", safe_category)
    os.makedirs(upload_dir, exist_ok=True)

    clean_filename = re.sub(r"[^a-zA-Z0-9_\.-]", "_", filename)
    unique_name = f"{secrets.token_hex(8)}_{clean_filename}"
    file_path = os.path.join(upload_dir, unique_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    relative_url = f"/uploads/onboarding/{safe_category}/{unique_name}".replace("\\", "/")

    return APIResponse(
        success=True,
        message="File uploaded successfully.",
        data=FileUploadResponse(
            url=relative_url,
            filename=clean_filename,
            size=file_size,
            category=safe_category,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Invited Employee Self-Activation (Public / Rate-limited)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/validate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee onboarding token (canonical)",
    dependencies=[Depends(check_onboarding_rate_limit)],
)
async def validate_onboarding_token_alias(
    token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Validate employee onboarding token (canonical endpoint)."""
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
    try:
        _, data = await validate_employee_invitation_token(session=session, token=token)
        return APIResponse[dict](
            success=True,
            message="Token is valid.",
            data=data,
            errors=None,
        )
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


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
    """Activate employee account, create user, clear token, and perform auto-login."""
    from app.core.security import hash_password
    from app.services.token_service import TokenService
    from app.repositories.auth_repository import AuthRepository
    from app.models.employee_emergency_contact import EmployeeEmergencyContact
    from app.models.user import UserRole

    clean_token = payload.token.strip() if payload.token else ""
    token_masked = mask_token(clean_token)
    logger.info("activate_onboarding: request | token=%s", token_masked)

    try:
        employee, _ = await validate_employee_invitation_token(session=session, token=clean_token)
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    now = datetime.now(timezone.utc)
    password_hash = hash_password(payload.password)
    user_email = (employee.company_email or employee.personal_email).lower().strip()

    phone_to_use = payload.phone or employee.phone
    clean_phone = "".join(filter(str.isdigit, phone_to_use)) if phone_to_use else ""
    if len(clean_phone) > 10:
        clean_phone = clean_phone[-10:]

    user = None
    if employee.user_id:
        user_res = await session.execute(select(User).where(User.id == employee.user_id))
        user = user_res.scalar_one_or_none()

    if not user:
        user_res = await session.execute(
            select(User).where(
                (func.lower(User.email) == user_email) |
                (func.lower(User.email) == employee.personal_email.lower().strip())
            )
        )
        user = user_res.scalar_one_or_none()

    if user:
        user.password_hash = password_hash
        user.is_active = True
        user.is_verified = True
        user.must_change_password = False
        user.account_status = "ACTIVE"
        user.email_verification_token = None
        user.email_verification_expires_at = None
        if not user.email_verified_at:
            user.email_verified_at = now
        if not user.company_id and employee.company_id:
            user.company_id = employee.company_id
        session.add(user)
        await session.flush()
        employee.user_id = user.id
    else:
        if clean_phone:
            phone_check = await session.execute(
                select(User).where(User.phone == clean_phone, User.is_deleted.is_(False))
            )
            if phone_check.scalar_one_or_none():
                clean_phone = None

        db_role = getattr(UserRole, (employee.role or "").upper(), UserRole.EMPLOYEE) if hasattr(UserRole, (employee.role or "").upper()) else UserRole.EMPLOYEE

        user = User(
            id=uuid.uuid4(),
            company_id=employee.company_id,
            name=f"{employee.first_name} {employee.last_name}".strip(),
            email=user_email,
            phone=clean_phone or "0000000000",
            password_hash=password_hash,
            is_active=True,
            is_verified=True,
            role=db_role,
            account_status="ACTIVE",
            email_verified_at=now,
            onboarding_completed=True,
            must_change_password=False,
            email_verification_token=None,
            email_verification_expires_at=None,
        )
        session.add(user)
        await session.flush()
        employee.user_id = user.id

    employee.status = "ACTIVE"
    employee.is_active = True
    employee.activation_token = None
    employee.activation_token_expires_at = None

    # Also update EmployeeInvitation table status to ACCEPTED
    inv_res = await session.execute(
        select(EmployeeInvitation).where(
            EmployeeInvitation.company_id == employee.company_id,
            func.lower(EmployeeInvitation.email) == user_email,
            EmployeeInvitation.status == "PENDING"
        )
    )
    for inv in inv_res.scalars().all():
        inv.status = "ACCEPTED"

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

    token_service = TokenService(session=session, auth_repository=AuthRepository(session))
    access_token, refresh_token, expires_in = await token_service.generate_auth_tokens(
        user_id=user.id,
        role=user.role,
        company_id=user.company_id,
    )

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
