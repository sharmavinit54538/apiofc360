"""Talent Pool and Candidate API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status, UploadFile, File
from fastapi.responses import Response

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    CandidateCreate,
    CandidateUpdate,
    CandidateResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/candidates", tags=["Candidate Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CandidateResponse],
    summary="Create a new candidate profile",
)
async def create_candidate(
    payload: CandidateCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateResponse]:
    """Create candidate profile. Admin and HR only."""
    cand = await service.create_candidate(payload)
    return APIResponse[CandidateResponse](
        success=True,
        message="Candidate profile created successfully.",
        data=cand,
        errors=None,
    )


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateResponse],
    summary="Retrieve candidate profile",
)
async def get_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateResponse]:
    """Get candidate profile detail. Admin and HR only."""
    cand = await service.get_candidate(id)
    return APIResponse[CandidateResponse](
        success=True,
        message="Candidate profile retrieved successfully.",
        data=cand,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List candidates with pagination and filters",
)
async def list_candidates(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    is_talent_pool: bool | None = Query(None),
    search: str | None = Query(None),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
) -> APIResponse[dict]:
    """List candidates. Admin and HR only."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    res = await service.list_candidates(
        is_talent_pool=is_talent_pool,
        search=search,
        tag=tag,
        page=page,
        limit=limit,
        company_id=company_id,
    )
    return APIResponse[dict](
        success=True,
        message="Candidates list retrieved successfully.",
        data=res,
        errors=None,
    )


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateResponse],
    summary="Update candidate profile",
)
async def update_candidate(
    id: uuid.UUID,
    payload: CandidateUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CandidateResponse]:
    """Update candidate details. Admin and HR only."""
    cand = await service.update_candidate(id, payload)
    return APIResponse[CandidateResponse](
        success=True,
        message="Candidate profile updated successfully.",
        data=cand,
        errors=None,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete candidate profile",
)
async def delete_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Delete candidate profile. Admin and HR only."""
    await service.delete_candidate(id)
    return APIResponse[None](
        success=True,
        message="Candidate profile deleted successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/import",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[int],
    summary="Import candidates from CSV",
)
async def import_candidates(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    file: UploadFile = File(...),
) -> APIResponse[int]:
    """Import candidates into talent pool from CSV. Admin and HR only."""
    content = await file.read()
    count = await service.import_candidates_csv(content.decode("utf-8"))
    return APIResponse[int](
        success=True,
        message=f"Successfully imported {count} candidates.",
        data=count,
        errors=None,
    )


@router.get(
    "/export/csv",
    summary="Export candidates to CSV",
)
async def export_candidates(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> Response:
    """Export all candidates to CSV. Admin and HR only."""
    csv_data = await service.export_candidates_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=candidates_export.csv"},
    )
