"""Interview Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    CompleteRoundRequest,
    InterviewResponse,
    InterviewScheduleCreate,
    InterviewScheduleResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(tags=["Interview Management"])

@router.post(
    "/applications/{id}/send-interview",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[InterviewResponse],
    summary="Initiate interview process",
)
async def send_interview(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    round_names: list[str] = Query(..., description="Order list of round names, e.g. Technical Round 1, System Design, HR"),
) -> APIResponse[InterviewResponse]:
    """Create interview record, configured rounds, and send invitation email. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    interview = await service.initiate_interview(user_id, id, round_names)
    return APIResponse[InterviewResponse](
        success=True,
        message="Interview invitation sent and rounds initialized.",
        data=interview,
        errors=None,
    )

@router.post(
    "/interviews/{id}/schedule",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[InterviewScheduleResponse],
    summary="Candidate books interview schedule slot",
)
async def schedule_interview_slot(
    id: uuid.UUID,
    payload: InterviewScheduleCreate,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewScheduleResponse]:
    """Candidate schedules slot within next 7 days. Prevents double booking. Public / Unauthenticated endpoint."""
    sched = await service.book_interview_schedule(id, payload)
    return APIResponse[InterviewScheduleResponse](
        success=True,
        message="Interview scheduled successfully.",
        data=sched,
        errors=None,
    )

@router.get(
    "/interviews",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[InterviewResponse]],
    summary="List all interviews",
)
async def list_interviews(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[InterviewResponse]]:
    """List interviews. Admin and HR only."""
    result = await service.list_interviews(status_filter, page, limit)
    return APIResponse[list[InterviewResponse]](
        success=True,
        message="Interviews retrieved successfully.",
        data=result,
        errors=None,
    )

@router.get(
    "/interviews/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewResponse],
    summary="Get interview details",
)
async def get_interview(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewResponse]:
    """Retrieve full interview rounds and schedules tracking. Admin and HR only."""
    interview = await service.get_interview(id)
    return APIResponse[InterviewResponse](
        success=True,
        message="Interview details retrieved successfully.",
        data=interview,
        errors=None,
    )

@router.patch(
    "/interviews/rounds/{round_id}/pass",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewResponse],
    summary="Pass interview round",
)
async def pass_round(
    round_id: uuid.UUID,
    payload: CompleteRoundRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewResponse]:
    """Mark interview round as passed. Transitions to next round index or completes interview. Admin and HR only."""
    interview = await service.complete_interview_round(round_id, "PASSED", payload)
    return APIResponse[InterviewResponse](
        success=True,
        message="Round passed successfully.",
        data=interview,
        errors=None,
    )

@router.patch(
    "/interviews/rounds/{round_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewResponse],
    summary="Reject interview round",
)
async def reject_round(
    round_id: uuid.UUID,
    payload: CompleteRoundRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewResponse]:
    """Mark interview round as rejected. Rejects candidate application. Admin and HR only."""
    interview = await service.complete_interview_round(round_id, "REJECTED", payload)
    return APIResponse[InterviewResponse](
        success=True,
        message="Round rejected. Candidate application updated to REJECTED.",
        data=interview,
        errors=None,
    )

@router.patch(
    "/interviews/rounds/{round_id}/hold",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewResponse],
    summary="Hold interview round",
)
async def hold_round(
    round_id: uuid.UUID,
    payload: CompleteRoundRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewResponse]:
    """Mark interview round status as Hold. Admin and HR only."""
    interview = await service.complete_interview_round(round_id, "HOLD", payload)
    return APIResponse[InterviewResponse](
        success=True,
        message="Round put on hold.",
        data=interview,
        errors=None,
    )
