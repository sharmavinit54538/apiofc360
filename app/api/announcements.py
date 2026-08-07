"""Announcements API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.communication import (
    AnnouncementCreate,
    AnnouncementResponse,
)
from app.services.communication_service import CommunicationService, get_communication_service

router = APIRouter(prefix="/announcements", tags=["Announcements Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AnnouncementResponse],
    summary="Create announcement",
)
async def create_announcement(
    payload: AnnouncementCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[AnnouncementResponse]:
    """Create a new announcement draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_announcement(user_id, payload)
    return APIResponse[AnnouncementResponse](
        success=True,
        message="Announcement draft created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AnnouncementResponse]],
    summary="List announcements",
)
async def list_announcements(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = Query(None),
    department: str | None = Query(None),
    branch: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[AnnouncementResponse]]:
    """List announcements with pagination and filter options."""
    res = await service.list_announcements(
        status=status_filter,
        priority=priority,
        department=department,
        branch=branch,
        search=search,
        page=page,
        limit=limit,
    )
    return APIResponse[list[AnnouncementResponse]](
        success=True,
        message="Announcements retrieved successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnnouncementResponse],
    summary="Get announcement details",
)
async def get_announcement(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[AnnouncementResponse]:
    """Get full details of announcement. Triggers read receipt."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.get_announcement(user_id, id)
    return APIResponse[AnnouncementResponse](
        success=True,
        message="Announcement details retrieved.",
        data=res,
        errors=None,
    )

@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnnouncementResponse],
    summary="Update announcement parameters",
)
async def update_announcement(
    id: uuid.UUID,
    payload: AnnouncementCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[AnnouncementResponse]:
    """Update details of announcement draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.update_announcement(user_id, id, payload)
    return APIResponse[AnnouncementResponse](
        success=True,
        message="Announcement updated successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete announcement",
)
async def delete_announcement(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[None]:
    """Soft delete announcement. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.delete_announcement(user_id, id)
    return APIResponse[None](
        success=True,
        message="Announcement deleted successfully.",
        data=None,
        errors=None,
    )

@router.patch(
    "/{id}/publish",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnnouncementResponse],
    summary="Publish announcement",
)
async def publish_announcement(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[AnnouncementResponse]:
    """Publish announcement draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.publish_announcement(user_id, id)
    return APIResponse[AnnouncementResponse](
        success=True,
        message="Announcement published successfully.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/archive",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnnouncementResponse],
    summary="Archive announcement",
)
async def archive_announcement(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[AnnouncementResponse]:
    """Archive announcement draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.archive_announcement(user_id, id)
    return APIResponse[AnnouncementResponse](
        success=True,
        message="Announcement archived.",
        data=res,
        errors=None,
    )
