"""Applicant Tracking System (ATS) Pipeline API Router."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ats", tags=["Applicant Tracking System (ATS) Pipeline"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List ATS candidates & pipeline entries",
)
@router.get(
    "/candidates",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List ATS candidates (Alias)",
)
async def get_ats_candidates(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    search: str | None = Query(None, description="Search candidate name, email, phone, job, department, or application ID"),
    stage: str | None = Query(None, description="Filter stage (Applied, Screening, Shortlisted, Interview, Technical, HR, Offer, Hired)"),
    status_filter: str | None = Query(None, alias="status", description="Filter application status (APPLIED, UNDER_REVIEW, SHORTLISTED, etc.)"),
    department: str | None = Query(None, description="Filter department"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> APIResponse[dict]:
    """Retrieve paginated ATS candidate pipeline entries with ATS scores, stages, and job details."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    result = await service.get_ats_pipeline_candidates(
        search=search,
        stage=stage,
        status_filter=status_filter,
        department=department,
        page=page,
        limit=limit,
        company_id=company_id,
    )

    return APIResponse[dict](
        success=True,
        message="ATS candidates retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/pipeline",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get ATS hiring pipeline board",
)
@router.get(
    "/board",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get ATS hiring pipeline board (Alias)",
)
async def get_ats_pipeline_board(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    search: str | None = Query(None, description="Search candidate name, email, job, or department"),
    department: str | None = Query(None, description="Filter department"),
) -> APIResponse[dict]:
    """Retrieve ATS pipeline kanban board grouped by stage with candidates list in each stage."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    result = await service.get_ats_pipeline_board(
        search=search,
        department=department,
        company_id=company_id,
    )

    return APIResponse[dict](
        success=True,
        message="ATS pipeline board retrieved successfully.",
        data=result,
        errors=None,
    )
