"""Company Events API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.communication import (
    CompanyEventCreate,
    CompanyEventResponse,
)
from app.services.communication_service import CommunicationService, get_communication_service

router = APIRouter(prefix="/events", tags=["Company Events Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CompanyEventResponse],
    summary="Create event",
)
async def create_event(
    payload: CompanyEventCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Schedule a new company event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_event(user_id, payload)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Event created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CompanyEventResponse]],
    summary="List events",
)
async def list_events(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
    status_filter: str | None = Query(None, alias="status"),
    event_type: str | None = Query(None),
) -> APIResponse[list[CompanyEventResponse]]:
    """List scheduled events."""
    res = await service.list_events(status=status_filter, event_type=event_type)
    return APIResponse[list[CompanyEventResponse]](
        success=True,
        message="Events retrieved successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyEventResponse],
    summary="Get event details",
)
async def get_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Retrieve full details of an event and registration counts."""
    res = await service.get_event(id)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Event details retrieved.",
        data=res,
        errors=None,
    )

@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyEventResponse],
    summary="Update event details",
)
async def update_event(
    id: uuid.UUID,
    payload: CompanyEventCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Update details of scheduled event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.update_event(user_id, id, payload)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Event updated successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete event",
)
async def delete_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[None]:
    """Delete scheduled event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.delete_event(user_id, id)
    return APIResponse[None](
        success=True,
        message="Event deleted successfully.",
        data=None,
        errors=None,
    )

@router.patch(
    "/{id}/publish",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyEventResponse],
    summary="Publish event",
)
async def publish_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Publish scheduled event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.repo.update_event(id, status="SCHEDULED")
    
    await service.repo.create_audit_log(
        user_id=user_id,
        action="PUBLISH",
        target_type="EVENT",
        target_id=id,
        details="Published event.",
    )
    
    await service.session.commit()
    updated = await service.repo.get_event_by_id(id)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Event published.",
        data=CompanyEventResponse.model_validate(updated),
        errors=None,
    )

@router.patch(
    "/{id}/cancel",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyEventResponse],
    summary="Cancel event",
)
async def cancel_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Cancel scheduled event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.repo.update_event(id, status="CANCELLED")
    
    await service.repo.create_audit_log(
        user_id=user_id,
        action="CANCEL",
        target_type="EVENT",
        target_id=id,
        details="Cancelled scheduled event.",
    )
    
    await service.session.commit()
    updated = await service.repo.get_event_by_id(id)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Event cancelled.",
        data=CompanyEventResponse.model_validate(updated),
        errors=None,
    )

@router.post(
    "/{id}/register",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyEventResponse],
    summary="Register for event",
)
async def register_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyEventResponse]:
    """Register currently logged in user to event. Enforces max participant limits."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.register_event_participant(user_id, id)
    return APIResponse[CompanyEventResponse](
        success=True,
        message="Successfully registered for the event.",
        data=res,
        errors=None,
    )
