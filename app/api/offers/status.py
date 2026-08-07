"""Job offer status acceptance/rejection endpoints."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status

from app.schemas.auth import APIResponse
from app.schemas.recruitment import OfferResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/offers")


@router.patch(
    "/{id}/accept",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OfferResponse],
    summary="Candidate accepts offer",
)
async def accept_offer(
    id: uuid.UUID,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[OfferResponse]:
    """Transition offer status to ACCEPTED. Public / Unauthenticated endpoint."""
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
    summary="Candidate rejects offer",
)
async def reject_offer(
    id: uuid.UUID,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[OfferResponse]:
    """Transition offer status to REJECTED. Public / Unauthenticated endpoint."""
    offer = await service.update_offer_status(id, "REJECTED")
    return APIResponse[OfferResponse](
        success=True,
        message="Job offer rejected.",
        data=offer,
        errors=None,
    )
