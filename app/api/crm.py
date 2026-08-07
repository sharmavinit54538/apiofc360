"""Candidate CRM API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    CandidateCrmNoteCreate,
    CandidateCrmNoteResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/crm", tags=["Recruitment CRM"])


@router.post(
    "/notes",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CandidateCrmNoteResponse],
    summary="Add a note to a candidate",
)
async def create_crm_note(
    payload: CandidateCrmNoteCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateCrmNoteResponse]:
    """Create a CRM note for a candidate profile. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    note = await service.create_crm_note(user_id, payload)
    return APIResponse[CandidateCrmNoteResponse](
        success=True,
        message="CRM note added successfully.",
        data=note,
        errors=None,
    )


@router.get(
    "/notes/{candidate_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CandidateCrmNoteResponse]],
    summary="List all notes for a candidate",
)
async def list_crm_notes(
    candidate_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[list[CandidateCrmNoteResponse]]:
    """List all touchpoint notes for a candidate. Admin and HR only."""
    notes = await service.list_crm_notes(candidate_id)
    return APIResponse[list[CandidateCrmNoteResponse]](
        success=True,
        message="CRM notes retrieved successfully.",
        data=notes,
        errors=None,
    )
