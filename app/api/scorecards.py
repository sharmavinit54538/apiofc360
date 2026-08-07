"""Recruitment Scorecards API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    ScorecardTemplateCreate,
    ScorecardTemplateResponse,
    ScorecardSubmissionCreate,
    ScorecardSubmissionResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/scorecards", tags=["Interview Scorecards"])


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ScorecardTemplateResponse],
    summary="Create scorecard template",
)
async def create_scorecard_template(
    payload: ScorecardTemplateCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ScorecardTemplateResponse]:
    """Create scorecard template. Admin and HR only."""
    tpl = await service.create_scorecard_template(payload)
    return APIResponse[ScorecardTemplateResponse](
        success=True,
        message="Scorecard template created successfully.",
        data=tpl,
        errors=None,
    )


@router.get(
    "/templates",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[ScorecardTemplateResponse]],
    summary="List scorecard templates",
)
async def list_scorecard_templates(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    department: str | None = Query(None),
) -> APIResponse[list[ScorecardTemplateResponse]]:
    """List scorecard templates. Admin and HR only."""
    templates = await service.list_scorecard_templates(department)
    return APIResponse[list[ScorecardTemplateResponse]](
        success=True,
        message="Scorecard templates retrieved successfully.",
        data=templates,
        errors=None,
    )


@router.post(
    "/submissions",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ScorecardSubmissionResponse],
    summary="Submit interview scorecard",
)
async def submit_scorecard(
    payload: ScorecardSubmissionCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ScorecardSubmissionResponse]:
    """Submit interview scorecard. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    submission = await service.submit_scorecard(user_id, payload)
    return APIResponse[ScorecardSubmissionResponse](
        success=True,
        message="Interview scorecard submitted successfully.",
        data=submission,
        errors=None,
    )


@router.get(
    "/submissions/{round_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[ScorecardSubmissionResponse]],
    summary="Get scorecards for an interview round",
)
async def get_scorecards(
    round_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[list[ScorecardSubmissionResponse]]:
    """Get scorecard submissions for round. Admin and HR only."""
    submissions = await service.get_scorecards_for_round(round_id)
    return APIResponse[list[ScorecardSubmissionResponse]](
        success=True,
        message="Scorecards retrieved successfully.",
        data=submissions,
        errors=None,
    )
