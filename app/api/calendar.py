"""Calendar Management API routes."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.calendar import (
    AnniversaryListItem,
    BirthdayListItem,
    CalendarDashboardView,
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
    HolidayCreate,
    HolidayResponse,
    MeetingCreate,
    MeetingResponse,
)
from app.services.calendar_service import CalendarService, get_calendar_service

router = APIRouter(prefix="/calendar", tags=["Calendar Management"])


# Helper dependency to enforce Manager, HR or Admin role
async def require_manager_or_hr_or_admin(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin", "manager"}:
        from app.core.exceptions import AppException
        raise AppException(message="Access denied.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


# ---------------------------------------------------------------------------
# Calendar Events Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CalendarEventResponse],
    summary="Create a new calendar event",
)
async def create_event(
    payload: CalendarEventCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[CalendarEventResponse]:
    """Create a new calendar event. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_event(user_id, payload)
    return APIResponse[CalendarEventResponse](
        success=True,
        message="Calendar event created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/events",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CalendarEventResponse]],
    summary="List calendar events",
)
async def list_events(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
    event_type: str | None = Query(None),
    department: str | None = Query(None),
    branch: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    visibility: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    search: str | None = Query(None),
) -> APIResponse[list[CalendarEventResponse]]:
    """List calendar events with filters."""
    res = await service.list_events(
        event_type=event_type,
        department=department,
        branch=branch,
        status=status_filter,
        visibility=visibility,
        start_date=start_date,
        end_date=end_date,
        search=search,
    )
    return APIResponse[list[CalendarEventResponse]](
        success=True,
        message="Calendar events retrieved successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/events/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CalendarEventResponse],
    summary="Get calendar event details",
)
async def get_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[CalendarEventResponse]:
    """Retrieve full details of a calendar event."""
    res = await service.get_event(id)
    return APIResponse[CalendarEventResponse](
        success=True,
        message="Calendar event details retrieved successfully.",
        data=res,
        errors=None,
    )

@router.put(
    "/events/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CalendarEventResponse],
    summary="Update calendar event",
)
async def update_event(
    id: uuid.UUID,
    payload: CalendarEventUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[CalendarEventResponse]:
    """Update calendar event details. Admin and HR only."""
    res = await service.update_event(id, payload)
    return APIResponse[CalendarEventResponse](
        success=True,
        message="Calendar event updated successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/events/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete calendar event",
)
async def delete_event(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[None]:
    """Soft delete a calendar event. Admin and HR only."""
    await service.delete_event(id)
    return APIResponse[None](
        success=True,
        message="Calendar event deleted successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Holidays Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/holidays",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[HolidayResponse],
    summary="Create a new holiday entry",
)
async def create_holiday(
    payload: HolidayCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[HolidayResponse]:
    """Create a new holiday entry. Admin and HR only."""
    res = await service.create_holiday(payload)
    return APIResponse[HolidayResponse](
        success=True,
        message="Holiday created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/holidays",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[HolidayResponse]],
    summary="List holidays",
)
async def list_holidays(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
    branch: str | None = Query(None),
    year: int | None = Query(None),
) -> APIResponse[list[HolidayResponse]]:
    """List holidays with branch or year filters."""
    res = await service.list_holidays(branch=branch, year=year)
    return APIResponse[list[HolidayResponse]](
        success=True,
        message="Holidays list retrieved.",
        data=res,
        errors=None,
    )

@router.put(
    "/holidays/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HolidayResponse],
    summary="Update holiday details",
)
async def update_holiday(
    id: uuid.UUID,
    payload: HolidayCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[HolidayResponse]:
    """Update holiday parameters. Admin and HR only."""
    res = await service.update_holiday(id, payload)
    return APIResponse[HolidayResponse](
        success=True,
        message="Holiday updated successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/holidays/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete holiday entry",
)
async def delete_holiday(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[None]:
    """Delete holiday record. Admin and HR only."""
    await service.delete_holiday(id)
    return APIResponse[None](
        success=True,
        message="Holiday deleted successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Meetings Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/meetings",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[MeetingResponse],
    summary="Schedule a meeting",
)
async def create_meeting(
    payload: MeetingCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[MeetingResponse]:
    """Schedule a meeting. Organizer double booking is automatically blocked."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_meeting(user_id, payload)
    return APIResponse[MeetingResponse](
        success=True,
        message="Meeting scheduled successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/meetings",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[MeetingResponse]],
    summary="List scheduled meetings",
)
async def list_meetings(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
    organizer_id: uuid.UUID | None = Query(None),
    meeting_date: date | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
) -> APIResponse[list[MeetingResponse]]:
    """List scheduled meetings."""
    res = await service.list_meetings(
        organizer_id=organizer_id,
        meeting_date=meeting_date,
        status=status_filter,
    )
    return APIResponse[list[MeetingResponse]](
        success=True,
        message="Meetings list retrieved.",
        data=res,
        errors=None,
    )

@router.get(
    "/meetings/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingResponse],
    summary="Get meeting details by ID",
)
async def get_meeting(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[MeetingResponse]:
    """Get full details of meeting and invited participants."""
    res = await service.get_meeting(id)
    return APIResponse[MeetingResponse](
        success=True,
        message="Meeting details retrieved successfully.",
        data=res,
        errors=None,
    )

@router.put(
    "/meetings/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingResponse],
    summary="Update scheduled meeting",
)
async def update_meeting(
    id: uuid.UUID,
    payload: MeetingCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[MeetingResponse]:
    """Update meeting parameters. Validates organizer overlaps."""
    res = await service.update_meeting(id, payload)
    return APIResponse[MeetingResponse](
        success=True,
        message="Meeting updated successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/meetings/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Cancel / delete meeting",
)
async def delete_meeting(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[None]:
    """Delete meeting schedule."""
    await service.delete_meeting(id)
    return APIResponse[None](
        success=True,
        message="Meeting cancelled successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Birthdays & Anniversaries Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/birthdays",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[BirthdayListItem]],
    summary="Get today's employee birthdays",
)
async def list_birthdays(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
    target_date: date | None = Query(None, description="Query date (defaults to today)"),
) -> APIResponse[list[BirthdayListItem]]:
    """List active employee birthdays today."""
    query_date = target_date or date.today()
    res = await service.get_birthdays(query_date)
    return APIResponse[list[BirthdayListItem]](
        success=True,
        message="Birthdays retrieved.",
        data=res,
        errors=None,
    )

@router.get(
    "/anniversaries",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AnniversaryListItem]],
    summary="Get today's employee work joining anniversaries",
)
async def list_anniversaries(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
    target_date: date | None = Query(None, description="Query date (defaults to today)"),
) -> APIResponse[list[AnniversaryListItem]]:
    """List active employee work anniversaries today."""
    query_date = target_date or date.today()
    res = await service.get_anniversaries(query_date)
    return APIResponse[list[AnniversaryListItem]](
        success=True,
        message="Anniversaries retrieved.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Dashboard Aggregations
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CalendarDashboardView],
    summary="Get calendar dashboard view",
)
async def get_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CalendarService, Depends(get_calendar_service)],
) -> APIResponse[CalendarDashboardView]:
    """Retrieve full unified calendar dashboard view for the caller."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.get_dashboard(user_id)
    return APIResponse[CalendarDashboardView](
        success=True,
        message="Calendar dashboard retrieved successfully.",
        data=res,
        errors=None,
    )
