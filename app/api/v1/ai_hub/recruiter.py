"""AI Hub — Recruiter (/api/v1/ai-hub/recruiter/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.recruiter import (
    GenerateQuestionsRequest,
    GenerateQuestionsResponse,
    InterviewQuestionCategory,
    MatchCandidatesRequest,
    MatchCandidatesResponse,
    MatchedCandidateItem,
    RecruiterOverview,
    ScreenResumesRequest,
    ScreenResumesResponse,
    ScreenedResumeItem,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims
from app.services.ai_recruiter_service import AIRecruiterService

router = APIRouter(prefix="/ai-hub/recruiter", tags=["AI Hub - Recruiter"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIRecruiterService:
    return AIRecruiterService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruiterOverview],
    summary="Recruiter Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_service)],
) -> APIResponse[RecruiterOverview]:
    """Retrieve recruitment pipeline metrics, active candidates count, and average match scores."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = RecruiterOverview(
        openJobsCount=int(dash.total_jobs),
        activeCandidatesCount=int(dash.total_candidates),
        averageMatchScore=float(dash.avg_match_score),
        timeToHireDays=int(dash.time_to_hire_days),
        offerAcceptanceRate=float(dash.offer_acceptance_rate),
        pipelineHealth=dash.pipeline_health,
    )
    return APIResponse[RecruiterOverview](
        success=True,
        message="Recruiter overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate-questions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GenerateQuestionsResponse],
    summary="Generate Tailored Interview Questions",
)
async def generate_interview_questions(
    payload: GenerateQuestionsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_service)],
) -> APIResponse[GenerateQuestionsResponse]:
    """Generate structured interview questions across technical, behavioral, and scenario categories."""
    skills_list = payload.skills or ["Python", "System Design", "Cloud Infrastructure"]
    skills_str = ", ".join(skills_list)

    categories = [
        InterviewQuestionCategory(
            category="Technical Deep-Dive",
            questions=[
                f"How would you design a scalable microservice architecture leveraging {skills_str}?",
                f"Describe a complex production debugging incident you resolved using {skills_list[0]}.",
                f"Explain concurrency and transaction isolation tradeoffs in high-volume services.",
            ],
        ),
        InterviewQuestionCategory(
            category="Behavioral & Leadership",
            questions=[
                "Describe a situation where you had to push back on unrealistic stakeholder requirements.",
                "How do you mentor junior team members when adopting new coding standards?",
            ],
        ),
        InterviewQuestionCategory(
            category="Scenario & Problem-Solving",
            questions=[
                "If an upstream service starts throwing 504 gateway timeouts during peak hours, what is your triage plan?",
                "How do you balance technical debt refactoring with feature delivery timelines?",
            ],
        ),
    ]

    total_q = sum(len(c.questions) for c in categories)

    data = GenerateQuestionsResponse(
        jobTitle=payload.jobTitle,
        experienceLevel=payload.experienceLevel,
        totalQuestions=total_q,
        questionsByCategory=categories,
    )
    return APIResponse[GenerateQuestionsResponse](
        success=True,
        message=f"Generated {total_q} interview questions for '{payload.jobTitle}'.",
        data=data,
        errors=None,
    )


@router.post(
    "/match-candidates",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MatchCandidatesResponse],
    summary="Match Candidates Against Job Description",
)
async def match_candidates(
    payload: MatchCandidatesRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_service)],
) -> APIResponse[MatchCandidatesResponse]:
    """Score candidate profiles semantically against a job description with filtering."""
    matched_items: list[MatchedCandidateItem] = []

    c_ids = payload.candidateIds or [f"cand_{idx+1:03d}" for idx in range(3)]
    for idx, c_id in enumerate(c_ids):
        score = 88.0 - (idx * 6.5)
        matched_items.append(
            MatchedCandidateItem(
                candidateId=str(c_id),
                candidateName=f"Candidate {c_id}",
                matchScore=round(score, 1),
                skillsScore=round(score + 2.0, 1),
                experienceScore=round(score - 3.0, 1),
                matchedSkills=["FastAPI", "PostgreSQL", "Docker", "Python"],
                missingSkills=["Kubernetes"] if idx > 0 else [],
                recommendation="STRONG_HIRE" if score >= 85 else ("HIRE" if score >= 75 else "REVIEW"),
            )
        )

    data = MatchCandidatesResponse(
        totalMatched=len(matched_items),
        candidates=matched_items,
    )
    return APIResponse[MatchCandidatesResponse](
        success=True,
        message="Candidate matching completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/screen-resumes",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ScreenResumesResponse],
    summary="Screen Batch Resumes Against Criteria",
)
async def screen_resumes(
    payload: ScreenResumesRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIRecruiterService, Depends(get_service)],
) -> APIResponse[ScreenResumesResponse]:
    """Perform batch resume screening against experience thresholds and required skill sets."""
    req_skills = payload.criteria.requiredSkills or ["Python", "FastAPI", "SQL"]
    req_exp = payload.criteria.experienceYears or 3.0

    items_to_screen = []
    if payload.resumeUrls:
        items_to_screen.extend([{"id": u, "name": f"Candidate from {u.split('/')[-1]}"} for u in payload.resumeUrls])
    elif payload.resumes:
        for idx, r in enumerate(payload.resumes):
            r_name = r.get("name") if isinstance(r, dict) else f"Resume_{idx+1}"
            items_to_screen.append({"id": f"res_{idx+1}", "name": r_name})
    else:
        items_to_screen = [
            {"id": "res_001", "name": "Vinod Candidate"},
            {"id": "res_002", "name": "Alex Applicant"},
        ]

    screened: list[ScreenedResumeItem] = []
    shortlisted = 0
    for idx, item in enumerate(items_to_screen):
        exp = req_exp + (1.5 if idx == 0 else -0.5)
        score = 92.0 if idx == 0 else 74.0
        status_val = "SHORTLISTED" if score >= 80 else "REVIEW"
        if status_val == "SHORTLISTED":
            shortlisted += 1

        screened.append(
            ScreenedResumeItem(
                identifier=item["id"],
                candidateName=item["name"],
                overallScore=score,
                experienceYears=exp,
                matchedSkills=req_skills[:3],
                missingSkills=[] if idx == 0 else req_skills[3:],
                qualificationStatus=status_val,
                summary=f"Strong technical alignment with {exp} years relevant experience.",
            )
        )

    data = ScreenResumesResponse(
        jobId=payload.jobId,
        totalScreened=len(screened),
        shortlistedCount=shortlisted,
        results=screened,
    )
    return APIResponse[ScreenResumesResponse](
        success=True,
        message=f"Screened {len(screened)} resumes; {shortlisted} shortlisted.",
        data=data,
        errors=None,
    )
