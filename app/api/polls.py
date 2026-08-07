"""Polls API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.communication import (
    PollCreate,
    PollResponse,
)
from app.services.communication_service import CommunicationService, get_communication_service

router = APIRouter(prefix="/polls", tags=["Polls Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[PollResponse],
    summary="Create poll",
)
async def create_poll(
    payload: PollCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[PollResponse]:
    """Create a new poll. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_poll(user_id, payload)
    return APIResponse[PollResponse](
        success=True,
        message="Poll created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[PollResponse]],
    summary="List polls",
)
async def list_polls(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
    status_filter: str | None = Query(None, alias="status"),
) -> APIResponse[list[PollResponse]]:
    """List polls."""
    res = await service.list_polls(status_filter)
    return APIResponse[list[PollResponse]](
        success=True,
        message="Polls retrieved.",
        data=res,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PollResponse],
    summary="Get poll details",
)
async def get_poll(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[PollResponse]:
    """Get poll details with options."""
    res = await service.get_poll(id)
    return APIResponse[PollResponse](
        success=True,
        message="Poll details retrieved.",
        data=res,
        errors=None,
    )

@router.post(
    "/{id}/vote",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PollResponse],
    summary="Cast vote on a poll option",
)
async def cast_vote(
    id: uuid.UUID,
    option_id: uuid.UUID = Query(..., description="Option ID to vote for"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[CommunicationService, Depends(get_communication_service)] = None,
) -> APIResponse[PollResponse]:
    """Cast vote on a poll option. Validates duplication constraints."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.cast_poll_vote(user_id, id, option_id)
    return APIResponse[PollResponse](
        success=True,
        message="Vote casted successfully.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/close",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PollResponse],
    summary="Close poll",
)
async def close_poll(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[PollResponse]:
    """Close poll manually. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.close_poll(user_id, id)
    return APIResponse[PollResponse](
        success=True,
        message="Poll closed.",
        data=res,
        errors=None,
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete poll",
)
async def delete_poll(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[None]:
    """Delete poll. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.repo.delete_poll(id)
    
    await service.repo.create_audit_log(
        user_id=user_id,
        action="DELETE",
        target_type="POLL",
        target_id=id,
        details="Deleted poll.",
    )
    await service.session.commit()
    
    return APIResponse[None](
        success=True,
        message="Poll deleted successfully.",
        data=None,
        errors=None,
    )
