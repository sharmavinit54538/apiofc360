"""AI Resume Screening & ATS Matching API endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import rate_limiter
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_resume import (
    CandidateATSAnalysisResponse,
    CandidateJobMatchDetailResponse,
    CandidateListItemSchema,
    CandidateProfileDetailResponse,
    CandidateScreeningResponse,
    JobMatchRequest,
    JobMatchResponse,
    ResumeParseDirectRequest,
)
from app.schemas.auth import APIResponse
from app.services.ai_screening_pipeline_service import AIScreeningPipelineService

router = APIRouter(prefix="/recruitment", tags=["AI Resume Screening & ATS Matching"])


async def get_pipeline_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIScreeningPipelineService:
    return AIScreeningPipelineService(session=session)


async def check_resume_upload_rate_limit(request: Request) -> None:
    """Rate limit for resume upload endpoint: 10 requests per minute per user/IP."""
    allowed, retry_after, _ = await rate_limiter.check_custom_rate_limit(
        request, scope="recruitment_resume_upload", limit=10, window_seconds=60
    )
    if not allowed:
        from app.core.rate_limiter import RateLimitExceeded
        raise RateLimitExceeded(
            detail=f"Too many resume upload attempts. Please try again in {retry_after} seconds.",
            retry_after=retry_after,
        )


@router.post(
    "/resume/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=CandidateScreeningResponse,
    summary="Upload resume for automated AI screening & ATS matching",
    dependencies=[Depends(check_resume_upload_rate_limit)],
)
@router.post(
    "/resumes/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=CandidateScreeningResponse,
    summary="Upload resume for automated AI screening & ATS matching (plural alias)",
    dependencies=[Depends(check_resume_upload_rate_limit)],
)
async def upload_and_screen_resume(
    file: UploadFile,
    job_id: uuid.UUID | None = Form(None, description="Optional target Job ID for ATS matching"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)] = None,
) -> CandidateScreeningResponse:
    """Upload resume (PDF, DOCX, DOC, TXT, PNG, JPG, JPEG), extract text, parse, clean, run quality & duplicate detection, compute ATS score, generate AI insights, and save structured records."""
    company_id_raw = claims.get("company_id") if claims else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    user_id_raw = claims.get("sub") if claims else None
    user_id = uuid.UUID(str(user_id_raw)) if user_id_raw else None

    return await service.process_resume_upload(
        file=file,
        job_id=job_id,
        company_id=company_id,
        uploaded_by=user_id,
    )


@router.post(
    "/resumes/parse",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Direct raw resume text parsing & dry-run analysis",
)
async def parse_resume_direct(
    payload: ResumeParseDirectRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
) -> APIResponse[dict]:
    """Directly parse raw resume text and return structured candidate profile, skills, and ATS analysis."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    result = await service.parse_resume_direct(
        raw_text=payload.raw_text or "",
        job_id=payload.job_id,
        company_id=company_id,
    )
    return APIResponse[dict](
        success=True,
        message="Resume parsed successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/candidates",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List all parsed candidates",
)
async def list_parsed_candidates(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
    search: str | None = Query(None, description="Search candidate name, email, or designation"),
    status_filter: str | None = Query(None, alias="status", description="Filter status (COMPLETED, PENDING, FAILED)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> APIResponse[dict]:
    """Retrieve paginated list of candidate profiles with ATS score, rank, and match tier."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    offset = (page - 1) * limit
    candidates, total = await service.repo.list_candidates(
        search=search,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        company_id=company_id,
    )

    items = [CandidateListItemSchema.model_validate(c).model_dump(mode="json") for c in candidates]
    return APIResponse[dict](
        success=True,
        message="Candidate list retrieved successfully.",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        },
        errors=None,
    )


@router.get(
    "/candidates/{candidate_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateProfileDetailResponse],
    summary="Get complete candidate profile",
)
async def get_candidate_profile(
    candidate_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
) -> APIResponse[CandidateProfileDetailResponse]:
    """Retrieve structured candidate resume, experience breakdown, education, skills, projects, certifications, ATS scores, and AI insights."""
    profile_data = await service.get_candidate_profile_full(candidate_id)
    return APIResponse[CandidateProfileDetailResponse](
        success=True,
        message="Candidate profile details retrieved successfully.",
        data=CandidateProfileDetailResponse.model_validate(profile_data),
        errors=None,
    )


@router.get(
    "/candidates/{candidate_id}/ats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateATSAnalysisResponse],
    summary="Get candidate ATS score breakdown & AI insights",
)
async def get_candidate_ats_analysis(
    candidate_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
) -> APIResponse[CandidateATSAnalysisResponse]:
    """Retrieve candidate ATS score breakdown, matched/missing skills, hiring recommendation, and interview questions."""
    ats_data = await service.get_candidate_ats_analysis(candidate_id)
    return APIResponse[CandidateATSAnalysisResponse](
        success=True,
        message="Candidate ATS analysis retrieved successfully.",
        data=CandidateATSAnalysisResponse.model_validate(ats_data),
        errors=None,
    )


@router.post(
    "/candidates/{candidate_id}/match/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateJobMatchDetailResponse],
    summary="Match a specific candidate against a target job description",
)
async def match_candidate_against_job(
    candidate_id: uuid.UUID,
    job_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
) -> APIResponse[CandidateJobMatchDetailResponse]:
    """Match candidate against target job and calculate multi-dimensional scores and recommendations."""
    result = await service.match_candidate_for_job(candidate_id=candidate_id, job_id=job_id)
    return APIResponse[CandidateJobMatchDetailResponse](
        success=True,
        message="Candidate matched against job successfully.",
        data=CandidateJobMatchDetailResponse.model_validate(result),
        errors=None,
    )


@router.post(
    "/jobs/{job_id}/match",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobMatchResponse],
    summary="Recalculate ATS scores & rankings for all candidates against job description",
)
async def match_candidates_for_job(
    job_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIScreeningPipelineService, Depends(get_pipeline_service)],
) -> APIResponse[JobMatchResponse]:
    """Recalculate ATS score, ranking, and matched/missing skills for all applicants against the selected Job Description."""
    result = await service.match_job_candidates(job_id)
    return APIResponse[JobMatchResponse](
        success=True,
        message="Job candidates matched and ranked successfully.",
        data=JobMatchResponse.model_validate(result),
        errors=None,
    )

