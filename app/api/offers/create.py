"""Job offer creation and candidate conversion endpoints."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import OfferCreate, OfferResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter()


@router.post(
    "/applications/{id}/offer",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[OfferResponse],
    summary="Create and release job offer",
)
async def create_offer(
    id: uuid.UUID,
    payload: OfferCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[OfferResponse]:
    """Create offer record, generate placeholder offer letter document, and email candidate. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    offer = await service.create_offer(user_id, id, payload)
    return APIResponse[OfferResponse](
        success=True,
        message="Offer created and candidate notified.",
        data=offer,
        errors=None,
    )


@router.post(
    "/applications/{id}/convert",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Convert selected candidate to Employee record",
)
async def convert_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Create User account, Employee record, default onboarding checklist, and send welcome emails. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.convert_candidate_to_employee(user_id, id)
    return APIResponse[None](
        success=True,
        message="Candidate converted to Employee successfully. Activation credentials emailed.",
        data=None,
        errors=None,
    )
