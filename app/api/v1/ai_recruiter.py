"""FastAPI router for AI Recruiter module endpoints (/api/v1/ai/recruiter/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_recruiter import (
    CandidateRankRequest,
    CandidateRankResponse,
    CandidateScoreResponse,
    FunnelWeekItem,
    GenerateInterviewQuestionsRequest,
    GenerateInterviewQuestionsResponse,
    HiringRecommendationResponse,
    JDMatchRequest,
    JDMatchResponse,
    MatchDistributionResponse,
    RecruiterDashboardResponse,
    RecruitmentAnalyticsResponse,
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
)
from app.services.ai_recruiter_service import AIRecruiterService

router = APIRouter(prefix="/ai/recruiter", tags=["AI Recruiter"])


async def get_ai_recruiter_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIRecruiterService:
    return AIRecruiterService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruiterDashboardResponse],
    summary="Get AI Recruiter Dashboard KPIs",
)
async def get_recruiter_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[RecruiterDashboardResponse]:
    """Retrieve dynamic dashboard KPIs: Open Roles, Candidates Screened, Top Matches, Average Time To Hire."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[RecruiterDashboardResponse](
        success=True,
        message="Recruiter dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/funnel",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[FunnelWeekItem]],
    summary="Get Candidate Funnel Chart data",
)
async def get_recruiter_funnel(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[List[FunnelWeekItem]]:
    """Retrieve candidate funnel breakdown by week (Applied, Screened, Shortlisted, Interviewed, Selected, Rejected, Offer Sent, Offer Accepted)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_funnel(company_id=company_id)
    return APIResponse[List[FunnelWeekItem]](
        success=True,
        message="Candidate funnel data fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/match-distribution",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MatchDistributionResponse],
    summary="Get JD Match Distribution Buckets",
)
async def get_match_distribution(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[MatchDistributionResponse]:
    """Retrieve candidate match score distribution across 90-100, 80-89, 70-79, 60-69, Below 60 bands."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_match_distribution(company_id=company_id)
    return APIResponse[MatchDistributionResponse](
        success=True,
        message="JD match distribution fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentAnalyticsResponse],
    summary="Get Recruitment Analytics",
)
async def get_recruitment_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[RecruitmentAnalyticsResponse]:
    """Retrieve time-to-hire, time-to-fill, source of hire, department breakdown, hiring trend, offer acceptance rate, and interview success rate."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[RecruitmentAnalyticsResponse](
        success=True,
        message="Recruitment analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/candidate/{id}/score",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateScoreResponse],
    summary="Get Candidate Multi-Dimensional Score",
)
async def get_candidate_score(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[CandidateScoreResponse]:
    """Retrieve overall score, skill score, experience score, culture score, communication score, and growth score for candidate."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_candidate_score(candidate_id=id, company_id=company_id)
    return APIResponse[CandidateScoreResponse](
        success=True,
        message="Candidate score fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/candidate/{id}/recommendation",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HiringRecommendationResponse],
    summary="Get AI Hiring Recommendation for Candidate",
)
async def get_candidate_recommendation(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[HiringRecommendationResponse]:
    """Retrieve hiring decision (STRONG_HIRE, HIRE, MAYBE, REJECT), confidence, reasoning, strengths, weaknesses, and risk analysis."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_candidate_recommendation(candidate_id=id, company_id=company_id)
    return APIResponse[HiringRecommendationResponse](
        success=True,
        message="Hiring recommendation fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/resume/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ResumeAnalyzeResponse],
    summary="Perform Automated Resume Screening & Skill Extraction",
)
async def analyze_resume(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
    file: Optional[UploadFile] = File(None),
    resume_id: Optional[uuid.UUID] = Form(None),
    candidate_id: Optional[uuid.UUID] = Form(None),
) -> APIResponse[ResumeAnalyzeResponse]:
    """Parse resume, extract skills, experience, education, certifications, and perform keyword matching."""
    company_id = get_company_id_from_claims(claims)
    user_id = uuid.UUID(claims.get("sub")) if claims.get("sub") else None

    data = await service.analyze_resume(
        file=file,
        resume_id=resume_id,
        candidate_id=candidate_id,
        company_id=company_id,
        uploaded_by=user_id,
    )
    return APIResponse[ResumeAnalyzeResponse](
        success=True,
        message="Resume analyzed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/match",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JDMatchResponse],
    summary="Perform Semantic JD-Candidate Matching",
)
async def match_jd(
    payload: JDMatchRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[JDMatchResponse]:
    """Calculate semantic match score, matched skills, missing skills, and hiring recommendation for candidate against Job."""
    company_id = get_company_id_from_claims(claims)
    data = await service.match_jd(
        job_id=payload.job_id, candidate_id=payload.candidate_id, company_id=company_id
    )
    return APIResponse[JDMatchResponse](
        success=True,
        message="JD match completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/rank",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateRankResponse],
    summary="Rank Candidates for Job Position",
)
async def rank_candidates(
    payload: CandidateRankRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[CandidateRankResponse]:
    """Rank candidates using skill match, experience, education, location, notice period, salary, and previous interview score."""
    company_id = get_company_id_from_claims(claims)
    data = await service.rank_candidates(
        job_id=payload.job_id, candidate_ids=payload.candidate_ids, company_id=company_id
    )
    return APIResponse[CandidateRankResponse](
        success=True,
        message="Candidates ranked successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/interview/questions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GenerateInterviewQuestionsResponse],
    summary="Generate AI Interview Questions",
)
async def generate_interview_questions(
    payload: GenerateInterviewQuestionsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_ai_recruiter_service)],
) -> APIResponse[GenerateInterviewQuestionsResponse]:
    """Generate tailored Technical, Behavioral, Scenario Based, and Managerial interview questions for candidate."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_interview_questions(
        job_id=payload.job_id, candidate_id=payload.candidate_id, company_id=company_id
    )
    return APIResponse[GenerateInterviewQuestionsResponse](
        success=True,
        message="Interview questions generated successfully.",
        data=data,
        errors=None,
    )
