"""Interview Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, status
from app.core.exceptions import AppException

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims_optional
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    CompleteRoundRequest,
    InterviewResponse,
    InterviewScheduleCreate,
    InterviewScheduleResponse,
    InterviewJoinResponse,
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
    "/interviews/schedule",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[InterviewScheduleResponse],
    summary="Candidate books interview schedule slot using invitation token",
)
async def schedule_interview_slot(
    payload: InterviewScheduleCreate,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewScheduleResponse]:
    """Candidate schedules slot using secure invitation token. Validates token ownership, expiry, and session status. Public / Unauthenticated endpoint."""
    if not payload.invitation_token:
        raise AppException(message="Invitation token is required.", status_code=status.HTTP_400_BAD_REQUEST)
    sched = await service.book_interview_schedule_by_token(payload)
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


# ===================================================================
# Candidate Interview Access Endpoints
# ===================================================================

@router.get(
    "/interviews/join/{token}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewJoinResponse],
    summary="Validate interview invitation token and get join details",
)
async def validate_interview_invitation(
    token: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[InterviewJoinResponse]:
    """Validate candidate interview invitation token and return join details. Public / Unauthenticated."""
    join_details = await service.validate_interview_invitation(token)
    return APIResponse[InterviewJoinResponse](
        success=True,
        message="Invitation validated successfully.",
        data=join_details,
        errors=None,
    )


@router.post(
    "/interviews/join/{token}/device-check",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Complete device check for interview",
)
async def complete_device_check(
    token: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    has_camera: bool = Form(...),
    has_microphone: bool = Form(...),
    camera_test_passed: bool = Form(...),
    microphone_test_passed: bool = Form(...),
    browser_info: str = Form(...),
) -> APIResponse[dict]:
    """Record candidate device check results. Public / Unauthenticated."""
    result = await service.complete_interview_device_check(
        token, has_camera, has_microphone, camera_test_passed, microphone_test_passed, browser_info
    )
    return APIResponse[dict](
        success=True,
        message="Device check completed.",
        data=result,
        errors=None,
    )


@router.post(
    "/interviews/join/{token}/consent",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Record candidate consent for interview recording",
)
async def record_consent(
    token: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    consent_given: bool = Form(...),
) -> APIResponse[dict]:
    """Record candidate consent for interview recording. Public / Unauthenticated."""
    result = await service.record_interview_consent(token, consent_given)
    return APIResponse[dict](
        success=True,
        message="Consent recorded." if consent_given else "Consent declined.",
        data=result,
        errors=None,
    )


@router.post(
    "/interviews/join/{token}/start",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Start interview session",
)
async def start_interview_session(
    token: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[dict]:
    """Start the interview session and return first question. Public / Unauthenticated."""
    result = await service.start_candidate_interview_session(token)
    return APIResponse[dict](
        success=True,
        message="Interview session started.",
        data=result,
        errors=None,
    )
