"""Employee Referrals API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    CandidateReferralCreate,
    CandidateReferralResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/referrals", tags=["Employee Referrals"])


class ReferralStatusUpdate(BaseModel):
    status: str
    reward_status: str | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CandidateReferralResponse],
    summary="Submit employee referral",
)
async def create_referral(
    payload: CandidateReferralCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateReferralResponse]:
    """Submit an employee referral. Admin and HR only."""
    ref = await service.create_referral(payload)
    return APIResponse[CandidateReferralResponse](
        success=True,
        message="Employee referral submitted successfully.",
        data=ref,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List all employee referrals",
)
async def list_referrals(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
) -> APIResponse[dict]:
    """List all referrals. Admin and HR only."""
    res = await service.list_referrals(page, limit)
    return APIResponse[dict](
        success=True,
        message="Employee referrals retrieved successfully.",
        data=res,
        errors=None,
    )


@router.put(
    "/{id}/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateReferralResponse],
    summary="Update employee referral status",
)
async def update_referral_status(
    id: uuid.UUID,
    payload: ReferralStatusUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateReferralResponse]:
    """Update referral and reward status. Admin and HR only."""
    ref = await service.update_referral_status(id, payload.status, payload.reward_status)
    return APIResponse[CandidateReferralResponse](
        success=True,
        message="Referral status updated successfully.",
        data=ref,
        errors=None,
    )
