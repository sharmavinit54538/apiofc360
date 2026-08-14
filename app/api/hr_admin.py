"""HR Admin User Management API Routes."""

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.exceptions import AppException
from app.core.rbac import require_admin
from app.schemas.auth import APIResponse
from app.schemas.hr_admin import (
    HRAdminCreateUserRequest,
    HRAdminUpdateUserRequest,
    HRAdminUserListResponse,
    HRAdminUserResponse,
)
from app.services.hr_admin_service import HRAdminService, get_hr_admin_service

router = APIRouter(prefix="/hr-admin", tags=["HR Admin User Management"])


def _extract_company_id(claims: dict) -> uuid.UUID:
    """Extract and validate the company_id from claims."""
    raw = claims.get("company_id")
    if not raw:
        raise AppException(
            message="Your account is not associated with a company organization.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise AppException(
            message="Invalid company association in token.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[HRAdminUserResponse],
    summary="Create internal company user",
    responses={
        status.HTTP_201_CREATED: {"model": APIResponse[HRAdminUserResponse], "description": "User created"},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Bad request"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden"},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None], "description": "User already exists"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Validation error"},
    },
)
async def create_user(
    payload: HRAdminCreateUserRequest,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
) -> APIResponse[HRAdminUserResponse]:
    """Create an internal company user (EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN) under the caller's organization."""

    admin_id = uuid.UUID(claims["sub"])
    company_id = _extract_company_id(claims)

    user = await service.create_user(admin_id=admin_id, company_id=company_id, payload=payload)

    return APIResponse[HRAdminUserResponse](
        success=True,
        message=f"User {user.email} ({user.role}) created successfully. Invitation email sent.",
        data=user,
        errors=None,
    )


@router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HRAdminUserListResponse],
    summary="List internal company users",
    responses={
        status.HTTP_200_OK: {"model": APIResponse[HRAdminUserListResponse], "description": "User list"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden"},
    },
)
async def list_users(
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
    role: Optional[str] = Query(None, description="Filter by role: employee, manager, executive, it_admin"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: ACTIVE, INVITED, SUSPENDED, DEACTIVATED"),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> APIResponse[HRAdminUserListResponse]:
    """List company users strictly isolated to the caller's organization."""

    company_id = _extract_company_id(claims)
    user_list = await service.list_users(
        company_id=company_id,
        role=role,
        status_filter=status_filter,
        search=search,
        page=page,
        page_size=page_size,
    )

    return APIResponse[HRAdminUserListResponse](
        success=True,
        message="Company users retrieved successfully.",
        data=user_list,
        errors=None,
    )


@router.get(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HRAdminUserResponse],
    summary="Get internal company user details",
    responses={
        status.HTTP_200_OK: {"model": APIResponse[HRAdminUserResponse], "description": "User details"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
    },
)
async def get_user(
    user_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
) -> APIResponse[HRAdminUserResponse]:
    """Retrieve details of a company user in the caller's organization."""

    company_id = _extract_company_id(claims)
    user = await service.get_user(target_user_id=user_id, company_id=company_id)

    return APIResponse[HRAdminUserResponse](
        success=True,
        message="User details retrieved successfully.",
        data=user,
        errors=None,
    )


@router.patch(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HRAdminUserResponse],
    summary="Update internal company user",
    responses={
        status.HTTP_200_OK: {"model": APIResponse[HRAdminUserResponse], "description": "User updated"},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Bad request"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden / Privilege escalation denied"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    payload: HRAdminUpdateUserRequest,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
) -> APIResponse[HRAdminUserResponse]:
    """Update details or status of a company user in the caller's organization."""

    admin_id = uuid.UUID(claims["sub"])
    company_id = _extract_company_id(claims)

    updated_user = await service.update_user(
        admin_id=admin_id,
        company_id=company_id,
        target_user_id=user_id,
        payload=payload,
    )

    return APIResponse[HRAdminUserResponse](
        success=True,
        message="User updated successfully.",
        data=updated_user,
        errors=None,
    )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Deactivate internal company user",
    responses={
        status.HTTP_200_OK: {"model": APIResponse[None], "description": "User deactivated"},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Cannot delete self"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
    },
)
async def delete_user(
    user_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
) -> APIResponse[None]:
    """Deactivate an internal company user in the caller's organization."""

    admin_id = uuid.UUID(claims["sub"])
    company_id = _extract_company_id(claims)

    await service.deactivate_user(admin_id=admin_id, company_id=company_id, target_user_id=user_id)

    return APIResponse[None](
        success=True,
        message="User deactivated successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/users/{user_id}/resend-invite",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Resend invitation email to internal company user",
    responses={
        status.HTTP_200_OK: {"model": APIResponse[None], "description": "Invitation resent"},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "User already verified"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Unauthorized"},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Forbidden"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
    },
)
async def resend_invite(
    user_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[HRAdminService, Depends(get_hr_admin_service)],
) -> APIResponse[None]:
    """Regenerate activation token and resend onboarding invite email to an invited user."""

    admin_id = uuid.UUID(claims["sub"])
    company_id = _extract_company_id(claims)

    await service.resend_invitation(admin_id=admin_id, company_id=company_id, target_user_id=user_id)

    return APIResponse[None](
        success=True,
        message="Invitation email resent successfully.",
        data=None,
        errors=None,
    )
