"""Manager Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.exceptions import AppException
from app.core.rbac import require_admin, require_admin_or_manager
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.manager import (
    ActivateManagerRequest,
    ManagerCreate,
    ManagerListResponse,
    ManagerResponse,
    ManagerUpdate,
    ActivateManagerOnboardingRequest,
    ManagerOnboardingCompleteRequest,
)
from app.services.manager_service import ManagerService, get_manager_service

router = APIRouter(prefix="/managers", tags=["Manager Management"])

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ManagerResponse],
    summary="Create a new manager",
    responses={
        status.HTTP_201_CREATED: {"model": APIResponse[ManagerResponse]},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None]},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None]},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None]},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None]},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None]},
    },
)
async def create_manager(
    payload: ManagerCreate,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Create a new manager record and linked inactive User. Sends an activation email. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    manager = await service.create_manager(admin_id, payload)
    return APIResponse[ManagerResponse](
        success=True,
        message="Manager created successfully. Activation email sent.",
        data=manager,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerListResponse],
    summary="List all managers",
)
async def list_managers(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
    department: str | None = Query(None, description="Filter by department"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    employment_type: str | None = Query(None, description="Filter by employment type"),
    search: str | None = Query(None, description="Search across names, ID, and emails"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=20000, description="Records per page"),
) -> APIResponse[ManagerListResponse]:
    """Retrieve a paginated, filterable list of manager records. Admin only."""
    result = await service.list_managers(
        department=department,
        status_filter=status_filter,
        employment_type=employment_type,
        search=search,
        page=page,
        limit=limit,
    )
    return APIResponse[ManagerListResponse](
        success=True,
        message="Managers retrieved successfully.",
        data=result,
        errors=None,
    )

@router.get(
    "/onboarding/validate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate manager onboarding token",
)
async def validate_manager_onboarding_token(
    token: str = Query(..., min_length=10),
    service: Annotated[ManagerService, Depends(get_manager_service)] = None,
) -> APIResponse[dict]:
    """Validate that the onboarding token is valid, not expired, and belongs to an invited manager."""
    try:
        data = await service.validate_onboarding_token(token)
        return APIResponse[dict](
            success=True,
            message="Token is valid.",
            data=data,
            errors=None,
        )
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "/validate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate manager activation token (canonical alias)",
)
async def validate_manager_token_alias(
    token: str = Query(..., min_length=10),
    service: Annotated[ManagerService, Depends(get_manager_service)] = None,
) -> APIResponse[dict]:
    """Canonical alias for validating manager activation/invitation token."""
    return await validate_manager_onboarding_token(token=token, service=service)


@router.get(
    "/validate-token",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate manager activation token (alias)",
)
async def validate_manager_token_alias2(
    token: str = Query(..., min_length=10),
    service: Annotated[ManagerService, Depends(get_manager_service)] = None,
) -> APIResponse[dict]:
    """Alias for validating manager activation/invitation token."""
    return await validate_manager_onboarding_token(token=token, service=service)


@router.post(
    "/onboarding/activate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Activate invited manager account",
)
async def activate_manager_onboarding(
    payload: ActivateManagerOnboardingRequest,
    service: Annotated[ManagerService, Depends(get_manager_service)] = None,
) -> APIResponse[dict]:
    """Activate manager account, create user, delete token, and perform auto-login."""
    try:
        data = await service.activate_onboarding_manager(payload)
        return APIResponse[dict](
            success=True,
            message="Account activated successfully.",
            data=data,
            errors=None,
        )
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "/activate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Activate manager account with invitation token (canonical)",
)
async def activate_manager_canonical(
    payload: ActivateManagerOnboardingRequest,
    service: Annotated[ManagerService, Depends(get_manager_service)] = None,
) -> APIResponse[dict]:
    """Canonical activation endpoint: Submit activation token and password to activate manager account."""
    return await activate_manager_onboarding(payload=payload, service=service)


class SendInviteRequest(BaseModel):
    manager_id: uuid.UUID | None = Field(None, description="Manager ID to send invite to")
    email: str | None = Field(None, description="Manager personal/company email")


@router.get(
    "/profile",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerResponse],
    summary="Get current manager's profile",
)
async def get_manager_profile(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Get the profile of the currently logged in manager."""
    user_id = uuid.UUID(claims["sub"])
    profile = await service.get_manager_by_user_id(user_id)
    return APIResponse[ManagerResponse](
        success=True,
        message="Manager profile retrieved successfully.",
        data=profile,
        errors=None,
    )


@router.post(
    "/send-invite",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Resend manager invitation link by manager ID or email",
)
async def send_invite_by_id_or_email(
    payload: SendInviteRequest,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Generate a new activation token and resend the email invitation by ID or email. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    manager_uuid = payload.manager_id
    if not manager_uuid and payload.email:
        email_str = payload.email.strip().lower()
        mgr = await service.repo.get_by_personal_email(email_str) or await service.repo.get_by_company_email(email_str)
        if not mgr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found.")
        manager_uuid = mgr.id
    
    if not manager_uuid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either manager_id or email must be provided.")
        
    await service.send_invitation(admin_id, manager_uuid)
    return APIResponse[None](
        success=True,
        message="Invitation email sent successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerResponse],
    summary="Get manager by ID",
)
async def get_manager(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Retrieve full manager profile. Admin only."""
    manager = await service.get_manager(id)
    return APIResponse[ManagerResponse](
        success=True,
        message="Manager profile retrieved successfully.",
        data=manager,
        errors=None,
    )

@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerResponse],
    summary="Update manager details",
)
async def update_manager(
    id: uuid.UUID,
    payload: ManagerUpdate,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Partially update manager details. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    manager = await service.update_manager(admin_id, id, payload)
    return APIResponse[ManagerResponse](
        success=True,
        message="Manager updated successfully.",
        data=manager,
        errors=None,
    )


class ManagerPermissionsUpdate(BaseModel):
    """Payload to update only the permission flags of a manager."""
    can_approve_leave: bool | None = None
    can_approve_attendance: bool | None = None
    can_manage_employees: bool | None = None
    can_view_payroll: bool | None = None
    can_edit_departments: bool | None = None
    can_invite_users: bool | None = None
    can_manage_recruitment: bool | None = None
    can_manage_performance: bool | None = None


@router.patch(
    "/{id}/permissions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerResponse],
    summary="Update manager permissions",
)
async def update_manager_permissions(
    id: uuid.UUID,
    payload: ManagerPermissionsUpdate,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Update only the permission flags for a manager. Admin only.
    Sends only the fields you want to change — omitted fields are left unchanged.
    """
    admin_id = uuid.UUID(claims["sub"])
    # Only include fields explicitly set by caller (not None defaults)
    permission_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not permission_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one permission field must be provided.",
        )
    # Wrap in ManagerUpdate so the existing service handles it
    from app.schemas.manager import ManagerUpdate
    update_payload = ManagerUpdate(**permission_data)
    manager = await service.update_manager(admin_id, id, update_payload)
    return APIResponse[ManagerResponse](
        success=True,
        message="Manager permissions updated successfully.",
        data=manager,
        errors=None,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Soft delete a manager",
)
async def delete_manager(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Soft delete manager and revoke all active refresh tokens. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    await service.delete_manager(admin_id, id)
    return APIResponse[None](
        success=True,
        message="Manager deleted successfully.",
        data=None,
        errors=None,
    )

@router.post(
    "/{id}/send-invitation",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Resend manager invitation link",
)
async def send_invitation(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Generate a new activation token and resend the email invitation. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    await service.send_invitation(admin_id, id)
    return APIResponse[None](
        success=True,
        message="Invitation email sent successfully.",
        data=None,
        errors=None,
    )

@router.post(
    "/{id}/activate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Activate manager account",
)
async def activate_manager(
    id: uuid.UUID,
    payload: ActivateManagerRequest,
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Submit the activation token from email along with the chosen permanent password. Public endpoint."""
    await service.activate_manager(id, payload)
    return APIResponse[None](
        success=True,
        message="Account activated successfully. You can now log in.",
        data=None,
        errors=None,
    )

@router.post(
    "/{id}/reset-password",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Admin reset of manager password",
)
async def reset_password(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Admin-triggered password reset. Generates a temporary password and emails it to the manager."""
    admin_id = uuid.UUID(claims["sub"])
    await service.reset_manager_password(admin_id, id)
    return APIResponse[None](
        success=True,
        message="Manager password reset successfully. Temporary password emailed.",
        data=None,
        errors=None,
    )


@router.post(
    "/onboarding/complete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ManagerResponse],
    summary="Complete manager onboarding details",
)
async def complete_onboarding(
    payload: ManagerOnboardingCompleteRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[ManagerResponse]:
    """Saves all manager onboarding details, sets first login flag to false, and updates linked user account."""
    user_id = uuid.UUID(claims["sub"])
    manager = await service.complete_manager_onboarding(user_id, payload)
    return APIResponse[ManagerResponse](
        success=True,
        message="Onboarding completed successfully.",
        data=manager,
        errors=None,
    )


@router.post(
    "/{id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Deactivate manager account",
)
async def deactivate_manager(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Deactivate manager account. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    await service.deactivate_manager(admin_id, id)
    return APIResponse[None](
        success=True,
        message="Manager account deactivated successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/activate-by-admin",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Activate manager account by Admin",
)
async def activate_manager_by_admin(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[ManagerService, Depends(get_manager_service)],
) -> APIResponse[None]:
    """Activate manager account by Admin. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    await service.activate_manager_by_admin(admin_id, id)
    return APIResponse[None](
        success=True,
        message="Manager account activated successfully.",
        data=None,
        errors=None,
    )
