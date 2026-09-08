"""HR Admin Onboarding API routes.

Complete, production-ready backend onboarding system for HR Admin:
1. Admin Profile
2. Company Setup
3. Organization & Departments
4. Work Schedule & Leave Policies
5. Employee Invitations (Individual Only)
6. Review & Activate
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from typing import Annotated, Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, NotFoundException, ValidationException
from app.core.rbac import require_hr_admin
from app.db.database import get_db_session
from app.models.company import Company
from app.models.user import User
from app.schemas.auth import APIResponse
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
from app.services.hr_admin_onboarding_service import HRAdminOnboardingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hr-admin/onboarding", tags=["HR Admin Onboarding"])


# ─────────────────────────────────────────────────────────────────────────────
# Helper Dependency: Resolve Company ID and User ID from HR Admin Claims
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_hr_admin_context(
    claims: Annotated[dict, Depends(require_hr_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> tuple[uuid.UUID, uuid.UUID | None]:
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
        from sqlalchemy import select
        user_res = await session.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if user and user.company_id:
            company_id = user.company_id

    return user_id, company_id


# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin Profile APIs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=APIResponse[HRAdminProfileResponse], summary="Get HR Admin Profile")
@router.get("/admin-profile", response_model=APIResponse[HRAdminProfileResponse], summary="Get HR Admin Profile (Alias)")
async def get_admin_profile(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[HRAdminProfileResponse]:
    """Retrieve HR Admin profile data."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    profile = await service.get_admin_profile(user_id, company_id)
    return APIResponse(success=True, message="Admin profile retrieved successfully.", data=profile)


@router.post("/profile", response_model=APIResponse[HRAdminProfileResponse], summary="Create/Update HR Admin Profile")
@router.put("/profile", response_model=APIResponse[HRAdminProfileResponse], summary="Update HR Admin Profile")
@router.post("/admin-profile", response_model=APIResponse[HRAdminProfileResponse], summary="Create/Update Admin Profile (Alias)")
@router.put("/admin-profile", response_model=APIResponse[HRAdminProfileResponse], summary="Update Admin Profile (Alias)")
async def update_admin_profile(
    payload: HRAdminProfileInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[HRAdminProfileResponse]:
    """Create or update HR Admin profile with validation and organization association."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    # If company does not exist yet, auto-provision a default company container
    if not company_id:
        user = await service.get_user(user_id)
        new_comp = Company(
            id=uuid.uuid4(),
            name=f"{payload.first_name}'s Organization",
            onboarding_completed=False,
            onboarding_step=1,
            company_profile={},
        )
        setattr(new_comp, "status", "PENDING")
        session.add(new_comp)
        await session.flush()
        user.company_id = new_comp.id
        company_id = new_comp.id

    profile = await service.update_admin_profile(user_id, company_id, payload)
    return APIResponse(success=True, message="Admin profile updated successfully.", data=profile)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Organization / Company APIs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/organization", response_model=APIResponse[OrganizationResponse], summary="Get Organization")
@router.get("/company", response_model=APIResponse[OrganizationResponse], summary="Get Company (Alias)")
async def get_organization(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OrganizationResponse]:
    """Retrieve organization data for the authenticated HR Admin."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization associated with this account.")
    service = HRAdminOnboardingService(session)
    org = await service.get_organization(company_id)
    return APIResponse(success=True, message="Organization retrieved successfully.", data=org)


@router.post("/organization", response_model=APIResponse[OrganizationResponse], summary="Create Organization")
@router.post("/company", response_model=APIResponse[OrganizationResponse], summary="Create Company (Alias)")
async def create_organization(
    payload: OrganizationInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OrganizationResponse]:
    """Create a new organization or update existing if already associated."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    if company_id:
        org = await service.update_organization(company_id, payload)
    else:
        org = await service.create_organization(user_id, payload)
    return APIResponse(success=True, message="Organization saved successfully.", data=org)


@router.put("/organization", response_model=APIResponse[OrganizationResponse], summary="Update Organization")
@router.patch("/organization", response_model=APIResponse[OrganizationResponse], summary="Patch Organization")
@router.put("/company", response_model=APIResponse[OrganizationResponse], summary="Update Company (Alias)")
async def update_organization(
    payload: OrganizationInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OrganizationResponse]:
    """Update organization details."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)
    if not company_id:
        org = await service.create_organization(user_id, payload)
    else:
        org = await service.update_organization(company_id, payload)
    return APIResponse(success=True, message="Organization updated successfully.", data=org)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Departments CRUD (Organization-level Isolation, No Demo Records)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/departments", response_model=APIResponse[DepartmentItemResponse], status_code=status.HTTP_201_CREATED, summary="Create Department")
async def create_department(
    payload: DepartmentCreateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DepartmentItemResponse]:
    """Create a new department belonging strictly to HR Admin's organization."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    dept = await service.create_department(company_id, user_id, payload)
    return APIResponse(success=True, message="Department created successfully.", data=dept)


@router.get("/departments", response_model=APIResponse[List[DepartmentItemResponse]], summary="Get Departments")
async def list_departments(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[List[DepartmentItemResponse]]:
    """List departments belonging ONLY to this organization."""
    user_id, company_id = context
    if not company_id:
        return APIResponse(success=True, message="Departments retrieved.", data=[])
    service = HRAdminOnboardingService(session)
    depts = await service.list_departments(company_id)
    return APIResponse(success=True, message="Departments retrieved successfully.", data=depts)


@router.get("/departments/{department_id}", response_model=APIResponse[DepartmentItemResponse], summary="Get Department by ID")
async def get_department(
    department_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DepartmentItemResponse]:
    """Get single department details."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    service = HRAdminOnboardingService(session)
    dept = await service.get_department(company_id, department_id)
    return APIResponse(success=True, message="Department retrieved.", data=dept)


@router.put("/departments/{department_id}", response_model=APIResponse[DepartmentItemResponse], summary="Update Department")
@router.patch("/departments/{department_id}", response_model=APIResponse[DepartmentItemResponse], summary="Patch Department")
async def update_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DepartmentItemResponse]:
    """Update department details."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    service = HRAdminOnboardingService(session)
    dept = await service.update_department(company_id, department_id, payload)
    return APIResponse(success=True, message="Department updated successfully.", data=dept)


@router.delete("/departments/{department_id}", response_model=APIResponse[Dict[str, Any]], summary="Delete Department")
async def delete_department(
    department_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[Dict[str, Any]]:
    """Delete department belonging to organization."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    service = HRAdminOnboardingService(session)
    await service.delete_department(company_id, department_id)
    return APIResponse(success=True, message="Department deleted successfully.", data={"id": str(department_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 4. Designations CRUD (Organization-level Ownership, Duplicate Protection)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/designations", response_model=APIResponse[DesignationItemResponse], status_code=status.HTTP_201_CREATED, summary="Create Designation")
async def create_designation(
    payload: DesignationCreateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DesignationItemResponse]:
    """Create a designation for the organization."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    desig = await service.create_designation(company_id, payload)
    return APIResponse(success=True, message="Designation created successfully.", data=desig)


@router.get("/designations", response_model=APIResponse[List[DesignationItemResponse]], summary="Get Designations")
async def list_designations(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[List[DesignationItemResponse]]:
    """List designations belonging to this organization."""
    user_id, company_id = context
    if not company_id:
        return APIResponse(success=True, message="Designations retrieved.", data=[])
    service = HRAdminOnboardingService(session)
    desigs = await service.list_designations(company_id)
    return APIResponse(success=True, message="Designations retrieved successfully.", data=desigs)


@router.get("/designations/{designation_id}", response_model=APIResponse[DesignationItemResponse], summary="Get Designation by ID")
async def get_designation(
    designation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DesignationItemResponse]:
    """Get designation details."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")
    service = HRAdminOnboardingService(session)
    desig = await service.get_designation(company_id, designation_id)
    return APIResponse(success=True, message="Designation retrieved.", data=desig)


@router.put("/designations/{designation_id}", response_model=APIResponse[DesignationItemResponse], summary="Update Designation")
@router.patch("/designations/{designation_id}", response_model=APIResponse[DesignationItemResponse], summary="Patch Designation")
async def update_designation(
    designation_id: uuid.UUID,
    payload: DesignationUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[DesignationItemResponse]:
    """Update designation."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")
    service = HRAdminOnboardingService(session)
    desig = await service.update_designation(company_id, designation_id, payload)
    return APIResponse(success=True, message="Designation updated successfully.", data=desig)


@router.delete("/designations/{designation_id}", response_model=APIResponse[Dict[str, Any]], summary="Delete Designation")
async def delete_designation(
    designation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[Dict[str, Any]]:
    """Delete designation."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found.")
    service = HRAdminOnboardingService(session)
    await service.delete_designation(company_id, designation_id)
    return APIResponse(success=True, message="Designation deleted successfully.", data={"id": str(designation_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 5. Organization Structure (Review Screen Snapshot)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/structure", response_model=APIResponse[OnboardingReviewResponse], summary="Get Organization Structure")
@router.get("/review", response_model=APIResponse[OnboardingReviewResponse], summary="Get Organization Review Structure")
@router.get("/organization/structure", response_model=APIResponse[OnboardingReviewResponse], summary="Get Structure")
async def get_organization_structure(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingReviewResponse]:
    """Return organization structure and review data for the onboarding review screen."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    service = HRAdminOnboardingService(session)
    structure = await service.get_organization_structure(company_id, user_id)
    return APIResponse(success=True, message="Organization structure retrieved successfully.", data=structure)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Work Schedule & HR Settings APIs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=APIResponse[WorkScheduleResponse], summary="Get HR Settings")
@router.get("/hr-settings", response_model=APIResponse[WorkScheduleResponse], summary="Get HR Settings (Alias)")
@router.get("/work-schedule", response_model=APIResponse[WorkScheduleResponse], summary="Get Work Schedule")
async def get_work_schedule(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[WorkScheduleResponse]:
    """Get HR settings and work schedule."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    service = HRAdminOnboardingService(session)
    sched = await service.get_work_schedule(company_id)
    return APIResponse(success=True, message="Work schedule settings retrieved.", data=sched)


@router.post("/settings", response_model=APIResponse[WorkScheduleResponse], summary="Save HR Settings")
@router.put("/settings", response_model=APIResponse[WorkScheduleResponse], summary="Update HR Settings")
@router.post("/hr-settings", response_model=APIResponse[WorkScheduleResponse], summary="Save HR Settings (Alias)")
@router.put("/hr-settings", response_model=APIResponse[WorkScheduleResponse], summary="Update HR Settings (Alias)")
@router.post("/work-schedule", response_model=APIResponse[WorkScheduleResponse], summary="Save Work Schedule")
@router.put("/work-schedule", response_model=APIResponse[WorkScheduleResponse], summary="Update Work Schedule")
async def update_work_schedule(
    payload: WorkScheduleInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[WorkScheduleResponse]:
    """Create or update Work Schedule and HR Settings with full validation."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    sched = await service.update_work_schedule(company_id, payload)
    return APIResponse(success=True, message="Work schedule settings saved successfully.", data=sched)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Leave Policies CRUD (Annual, Sick, Casual)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/leave-policies", response_model=APIResponse[LeavePolicyResponse], status_code=status.HTTP_201_CREATED, summary="Create Leave Policy")
async def create_leave_policy(
    payload: LeavePolicyCreateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[LeavePolicyResponse]:
    """Create a leave policy with organization isolation."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    policy = await service.create_leave_policy(company_id, payload)
    return APIResponse(success=True, message="Leave policy created successfully.", data=policy)


@router.get("/leave-policies", response_model=APIResponse[List[LeavePolicyResponse]], summary="Get Leave Policies")
async def list_leave_policies(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[List[LeavePolicyResponse]]:
    """List leave policies for organization."""
    user_id, company_id = context
    if not company_id:
        return APIResponse(success=True, message="Leave policies retrieved.", data=[])
    service = HRAdminOnboardingService(session)
    policies = await service.list_leave_policies(company_id)
    return APIResponse(success=True, message="Leave policies retrieved successfully.", data=policies)


@router.get("/leave-policies/{policy_id}", response_model=APIResponse[LeavePolicyResponse], summary="Get Leave Policy by ID")
async def get_leave_policy(
    policy_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[LeavePolicyResponse]:
    """Get single leave policy."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")
    service = HRAdminOnboardingService(session)
    policy = await service.get_leave_policy(company_id, policy_id)
    return APIResponse(success=True, message="Leave policy retrieved.", data=policy)


@router.put("/leave-policies/{policy_id}", response_model=APIResponse[LeavePolicyResponse], summary="Update Leave Policy")
@router.patch("/leave-policies/{policy_id}", response_model=APIResponse[LeavePolicyResponse], summary="Patch Leave Policy")
async def update_leave_policy(
    policy_id: uuid.UUID,
    payload: LeavePolicyUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[LeavePolicyResponse]:
    """Update leave policy."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")
    service = HRAdminOnboardingService(session)
    policy = await service.update_leave_policy(company_id, policy_id, payload)
    return APIResponse(success=True, message="Leave policy updated successfully.", data=policy)


@router.delete("/leave-policies/{policy_id}", response_model=APIResponse[Dict[str, Any]], summary="Delete Leave Policy")
async def delete_leave_policy(
    policy_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[Dict[str, Any]]:
    """Delete leave policy."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave policy not found.")
    service = HRAdminOnboardingService(session)
    await service.delete_leave_policy(company_id, policy_id)
    return APIResponse(success=True, message="Leave policy deleted successfully.", data={"id": str(policy_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 8. Individual Employee Invitations (STRICTLY INDIVIDUAL ONLY, NO BULK/CSV/EXCEL)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/invitations", response_model=APIResponse[InvitationResponse], status_code=status.HTTP_201_CREATED, summary="Send Individual Invitation")
@router.post("/invite-employee", response_model=APIResponse[InvitationResponse], status_code=status.HTTP_201_CREATED, summary="Send Invitation (Alias)")
async def send_individual_invitation(
    payload: IndividualInvitationInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[InvitationResponse]:
    """Send an individual employee invitation. Generates secure token and 7-day expiry. NO bulk/CSV import."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    inv = await service.send_individual_invitation(company_id, user_id, payload)
    return APIResponse(success=True, message="Employee invitation sent successfully.", data=inv)


@router.get("/invitations", response_model=APIResponse[List[InvitationResponse]], summary="Get Invitations")
@router.get("/invitations/pending", response_model=APIResponse[List[InvitationResponse]], summary="Get Pending Invitations")
async def list_pending_invitations(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[List[InvitationResponse]]:
    """List pending employee invitations."""
    user_id, company_id = context
    if not company_id:
        return APIResponse(success=True, message="Pending invitations retrieved.", data=[])
    service = HRAdminOnboardingService(session)
    invs = await service.list_pending_invitations(company_id)
    return APIResponse(success=True, message="Pending invitations retrieved successfully.", data=invs)


@router.post("/invitations/{invitation_id}/resend", response_model=APIResponse[InvitationResponse], summary="Resend Invitation")
async def resend_invitation(
    invitation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[InvitationResponse]:
    """Resend employee invitation with a refreshed secure token and reset expiry."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    service = HRAdminOnboardingService(session)
    inv = await service.resend_invitation(company_id, invitation_id)
    return APIResponse(success=True, message="Invitation resent successfully.", data=inv)


@router.post("/invitations/{invitation_id}/cancel", response_model=APIResponse[Dict[str, Any]], summary="Cancel Invitation")
@router.delete("/invitations/{invitation_id}", response_model=APIResponse[Dict[str, Any]], summary="Cancel Invitation (Delete Alias)")
async def cancel_invitation(
    invitation_id: uuid.UUID,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[Dict[str, Any]]:
    """Cancel a pending employee invitation."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    service = HRAdminOnboardingService(session)
    await service.cancel_invitation(company_id, invitation_id)
    return APIResponse(success=True, message="Invitation cancelled successfully.", data={"id": str(invitation_id)})


# ─────────────────────────────────────────────────────────────────────────────
# 9. Onboarding Progress & Status APIs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=APIResponse[OnboardingStatusResponse], summary="Get Onboarding Status")
async def get_onboarding_status(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingStatusResponse]:
    """Get current onboarding status, completion percentage, and active step."""
    user_id, company_id = context
    if not company_id:
        return APIResponse(
            success=True,
            message="Onboarding not started.",
            data=OnboardingStatusResponse(
                onboarding_completed=False,
                current_step=1,
                completion_percentage=0.0,
                status="not_started",
            ),
        )
    service = HRAdminOnboardingService(session)
    progress = await service.get_or_create_progress(company_id, user_id)
    resp = service._build_status_response(progress)
    return APIResponse(success=True, message="Onboarding status retrieved successfully.", data=resp)


@router.get("/progress", response_model=APIResponse[OnboardingProgressResponse], summary="Get All Onboarding Progress")
@router.get("", response_model=APIResponse[OnboardingProgressResponse], summary="Get Onboarding Data Root")
@router.get("/", response_model=APIResponse[OnboardingProgressResponse], summary="Get Onboarding Data Slash")
async def get_onboarding_progress(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingProgressResponse]:
    """Get all saved onboarding wizard data to prefill frontend forms on refresh/relogin."""
    user_id, company_id = context
    if not company_id:
        # Provision blank organization if missing
        service = HRAdminOnboardingService(session)
        user = await service.get_user(user_id)
        new_comp = Company(
            id=uuid.uuid4(),
            name="My Organization",
            onboarding_completed=False,
            onboarding_step=1,
            company_profile={},
        )
        setattr(new_comp, "status", "PENDING")
        session.add(new_comp)
        await session.flush()
        user.company_id = new_comp.id
        company_id = new_comp.id

    service = HRAdminOnboardingService(session)
    data = await service.get_progress_response(company_id, user_id)
    return APIResponse(success=True, message="Onboarding progress retrieved successfully.", data=data)


@router.put("/progress", response_model=APIResponse[OnboardingProgressResponse], summary="Save Onboarding Progress")
@router.patch("/progress", response_model=APIResponse[OnboardingProgressResponse], summary="Patch Onboarding Progress")
async def save_onboarding_progress(
    payload: OnboardingProgressUpdateInput,
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingProgressResponse]:
    """Persist onboarding step progress in the database."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created first.")
    service = HRAdminOnboardingService(session)
    data = await service.save_progress(company_id, user_id, payload.current_step, payload.completed_steps, payload.status)
    return APIResponse(success=True, message="Onboarding progress saved successfully.", data=data)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Complete Onboarding API (Transactional, Idempotent, Activates Workspace)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/complete", response_model=APIResponse[Dict[str, Any]], summary="Complete Onboarding & Activate Workspace")
async def complete_onboarding(
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[Dict[str, Any]]:
    """Complete HR Admin onboarding, seed required defaults, and activate organization workspace."""
    user_id, company_id = context
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization must be created before completing onboarding.")
    service = HRAdminOnboardingService(session)
    res = await service.complete_onboarding(company_id, user_id)
    return APIResponse(success=True, message=res["message"], data=res)


# ─────────────────────────────────────────────────────────────────────────────
# 11. File Upload (Company Logo, Stamp, Profile Photo)
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".svg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload", response_model=APIResponse[FileUploadResponse], summary="Upload Onboarding Asset File")
async def upload_onboarding_asset(
    file: UploadFile = File(...),
    category: str = Form(default="company_logo"),
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
) -> APIResponse[FileUploadResponse]:
    """Upload company logo, company stamp, or admin profile photo with strict validation."""
    user_id, company_id = context

    # 1. Validate file extension
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 2. Validate MIME type
    content_type = file.content_type or ""
    if content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME content-type '{content_type}'. Must be a valid image.",
        )

    # 3. Read and validate file size
    contents = await file.read()
    file_size = len(contents)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds 5MB limit.",
        )
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # 4. Save to secure folder
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
# 12. Compatibility Wizard Endpoints (Top-level & Step-Index)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=APIResponse[OnboardingProgressResponse], summary="Save Onboarding Wizard")
@router.post("/", response_model=APIResponse[OnboardingProgressResponse], summary="Save Onboarding Wizard Slash")
async def save_wizard_data(
    payload: Dict[str, Any],
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingProgressResponse]:
    """Compatibility endpoint for top-level wizard payload saving."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    if not company_id:
        comp_name = payload.get("company_name") or payload.get("companyName") or "My Company"
        new_comp = Company(
            id=uuid.uuid4(),
            name=str(comp_name).strip(),
            onboarding_completed=False,
            onboarding_step=1,
            company_profile=payload,
        )
        setattr(new_comp, "status", "PENDING")
        session.add(new_comp)
        await session.flush()
        user = await service.get_user(user_id)
        user.company_id = new_comp.id
        company_id = new_comp.id
    else:
        company = await service.get_company(company_id)
        prof = company.company_profile or {}
        prof.update(payload)
        company.company_profile = prof
        flag_modified(company, "company_profile")

    step_val = payload.get("current_step") or payload.get("step")
    if step_val:
        try:
            step_int = int(step_val)
            progress = await service.get_or_create_progress(company_id, user_id)
            progress.current_step = step_int
        except (ValueError, TypeError):
            pass

    await session.commit()
    data = await service.get_progress_response(company_id, user_id)
    return APIResponse(success=True, message="Onboarding wizard data saved successfully.", data=data)


@router.post("/step/{step_index}", response_model=APIResponse[OnboardingProgressResponse], summary="Save Step by Index")
async def save_step_by_index(
    step_index: int,
    payload: Dict[str, Any],
    context: tuple[uuid.UUID, uuid.UUID | None] = Depends(_resolve_hr_admin_context),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[OnboardingProgressResponse]:
    """Compatibility endpoint to save step by index."""
    user_id, company_id = context
    service = HRAdminOnboardingService(session)

    if not company_id:
        comp_name = payload.get("company_name") or payload.get("companyName") or "My Organization"
        new_comp = Company(
            id=uuid.uuid4(),
            name=str(comp_name).strip(),
            onboarding_completed=False,
            onboarding_step=step_index + 1,
            company_profile=payload,
        )
        setattr(new_comp, "status", "PENDING")
        session.add(new_comp)
        await session.flush()
        user = await service.get_user(user_id)
        user.company_id = new_comp.id
        company_id = new_comp.id

    progress = await service.get_or_create_progress(company_id, user_id)
    if progress.current_step <= step_index:
        progress.current_step = step_index + 1
    progress.status = "in_progress"

    await session.commit()
    data = await service.get_progress_response(company_id, user_id)
    return APIResponse(success=True, message=f"Step {step_index} saved successfully.", data=data)
