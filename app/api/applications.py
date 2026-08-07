"""Candidate Application Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr, require_admin_or_hr_or_manager
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    ApplicationListResponse,
    ApplicationResponse,
    RecruitmentDashboardStats,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/applications", tags=["Application Management"])


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentDashboardStats],
    summary="Get recruitment metrics dashboard",
)
async def get_recruitment_stats(
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[RecruitmentDashboardStats]:
    """Retrieve recruitment metrics counts. Admin, HR, and Managers."""
    stats = await service.get_dashboard_stats()
    return APIResponse[RecruitmentDashboardStats](
        success=True,
        message="Recruitment dashboard statistics retrieved successfully.",
        data=stats,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationListResponse],
    summary="List all applications",
)
async def list_applications(
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    job_id: uuid.UUID | None = Query(None, description="Filter by job ID"),
    status_filter: str | None = Query(None, alias="status", description="Filter by application status"),
    search: str | None = Query(None, description="Search by candidate name or email"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[ApplicationListResponse]:
    """List applications. Admin, HR, and Managers."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    result = await service.list_applications(
        job_id=job_id,
        status=status_filter,
        search=search,
        page=page,
        limit=limit,
        company_id=company_id,
    )
    return APIResponse[ApplicationListResponse](
        success=True,
        message="Applications retrieved successfully.",
        data=result,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationResponse],
    summary="Get application details",
)
async def get_application(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ApplicationResponse]:
    """Retrieve details of a candidate application. Admin and HR only."""
    app = await service.get_application(id)
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application details retrieved successfully.",
        data=app,
        errors=None,
    )

@router.patch(
    "/{id}/shortlist",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationResponse],
    summary="Shortlist candidate",
)
async def shortlist_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ApplicationResponse]:
    """Shortlist candidate application. Admin and HR only."""
    app = await service.update_application_status(id, "SHORTLISTED")
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application shortlisted successfully.",
        data=app,
        errors=None,
    )

@router.patch(
    "/{id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationResponse],
    summary="Reject candidate",
)
async def reject_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ApplicationResponse]:
    """Reject candidate application. Sends automated rejection email. Admin and HR only."""
    app = await service.update_application_status(id, "REJECTED")
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application rejected successfully.",
        data=app,
        errors=None,
    )

@router.patch(
    "/{id}/hold",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationResponse],
    summary="Put candidate on hold",
)
async def hold_candidate(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ApplicationResponse]:
    """Put candidate application on hold status. Admin and HR only."""
    app = await service.update_application_status(id, "HOLD")
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application put on hold successfully.",
        data=app,
        errors=None,
    )


from pydantic import BaseModel

class BulkMoveRequest(BaseModel):
    application_ids: list[uuid.UUID]
    status: str

class BulkTagRequest(BaseModel):
    candidate_ids: list[uuid.UUID]
    tags: list[str]

class StageUpdateRequest(BaseModel):
    stage: str


@router.patch(
    "/{id}/stage",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApplicationResponse],
    summary="Move application stage",
)
async def move_application_stage(
    id: uuid.UUID,
    payload: StageUpdateRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[ApplicationResponse]:
    """Change the current workflow stage (status) of an application. Admin and HR only."""
    app = await service.update_application_status(id, payload.stage)
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application stage updated successfully.",
        data=app,
        errors=None,
    )


@router.post(
    "/bulk-move",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Bulk move candidates",
)
async def bulk_move_candidates(
    payload: BulkMoveRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Bulk update candidate workflow stages. Admin and HR only."""
    await service.bulk_move_applications(payload.application_ids, payload.status)
    return APIResponse[None](
        success=True,
        message=f"Successfully moved {len(payload.application_ids)} candidates to stage {payload.status}.",
        data=None,
        errors=None,
    )


@router.post(
    "/bulk-tag",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Bulk tag candidates",
)
async def bulk_tag_candidates(
    payload: BulkTagRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Bulk tag candidates. Admin and HR only."""
    await service.bulk_tag_candidates(payload.candidate_ids, payload.tags)
    return APIResponse[None](
        success=True,
        message=f"Successfully tagged {len(payload.candidate_ids)} candidates.",
        data=None,
        errors=None,
    )
