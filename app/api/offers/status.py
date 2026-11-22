"""Job offer status acceptance/rejection endpoints with signed token verification."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.auth import APIResponse
from app.schemas.recruitment import OfferResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service
from app.utils.offer_token import verify_offer_action_token

router = APIRouter(prefix="/offers")


async def _verify_offer_token(
    id: uuid.UUID,
    token: Annotated[str, Query(..., description="Signed offer action token")],
    expected_action: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> dict:
    """Verify the offer action token and return the decoded payload."""
    payload = verify_offer_action_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or tampered offer action token.",
        )

    # Verify token matches the offer ID in the path
    if payload.get("offer_id") != str(id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not match the requested offer.",
        )

    # Verify action matches
    if payload.get("action") != expected_action:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token action does not match endpoint.",
        )

    # Verify offer exists and belongs to the company in token
    offer = await service.repo.get_offer_by_id(id)
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found.",
        )

    # Get application to verify company_id and candidate_email
    app = await service.repo.get_application_by_id(offer.application_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated application not found.",
        )

    if payload.get("company_id") != str(app.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token company mismatch.",
        )

    if payload.get("candidate_email", "").lower() != (app.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token candidate email mismatch.",
        )

    return payload


@router.patch(
    "/{id}/accept",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OfferResponse],
    summary="Candidate accepts offer (requires signed token)",
)
async def accept_offer(
    id: uuid.UUID,
    token: Annotated[str, Query(..., description="Signed offer action token")],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    _payload: Annotated[dict, Depends(_verify_offer_token)],
) -> APIResponse[OfferResponse]:
    """Transition offer status to ACCEPTED. Requires valid signed expiring token."""
    offer = await service.update_offer_status(id, "ACCEPTED")
    return APIResponse[OfferResponse](
        success=True,
        message="Job offer accepted.",
        data=offer,
        errors=None,
    )


@router.patch(
    "/{id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OfferResponse],
    summary="Candidate rejects offer (requires signed token)",
)
async def reject_offer(
    id: uuid.UUID,
    token: Annotated[str, Query(..., description="Signed offer action token")],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    _payload: Annotated[dict, Depends(_verify_offer_token)],
) -> APIResponse[OfferResponse]:
    """Transition offer status to REJECTED. Requires valid signed expiring token."""
    offer = await service.update_offer_status(id, "REJECTED")
    return APIResponse[OfferResponse](
        success=True,
        message="Job offer rejected.",
        data=offer,
        errors=None,
    )
