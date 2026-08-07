"""AI Hiring Copilot API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_copilot import (
    AiAnalysisResponse,
    AiCopilotDashboardView,
    CandidateRankingResponse,
    ExtractionDataResponse,
    InterviewQuestionsResponse,
    SemanticMatchResponse,
)
from app.services.ai_copilot_service import AiCopilotService, get_ai_copilot_service

router = APIRouter(prefix="/ai", tags=["AI Hiring Copilot"])


@router.post(
    "/upload-resume",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Stage 1 — Upload Candidate Resume",
)
async def upload_resume(
    file: UploadFile,
    application_id: str = Form(..., description="Application UUID"),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[dict]:
    """Upload candidate resume file (PDF/DOCX/PNG/JPG/JPEG, ≤10MB).

    Returns `resume_document_id` required for all subsequent pipeline stages.

    Accepted formats: PDF, DOCX, DOC, PNG, JPG, JPEG.
    """
    res = await service.upload_resume(uuid.UUID(application_id), file)
    return APIResponse[dict](
        success=True,
        message="Resume uploaded successfully.",
        data=res,
        errors=None,
    )


@router.post(
    "/extract",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExtractionDataResponse],
    summary="Stage 2 — Extract Structured Resume Data",
)
async def extract_resume(
    resume_document_id: uuid.UUID = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[ExtractionDataResponse]:
    """Extract raw text from uploaded resume and parse structured JSON via local Llama3.

    Extracts: Name, Email, Phone, Location, Skills, Experience, Education, Projects,
    Certifications, Achievements, Expected Salary, Notice Period.
    """
    res = await service.extract_resume(resume_document_id)
    return APIResponse[ExtractionDataResponse](
        success=True,
        message="Resume structured data extracted successfully.",
        data=res,
        errors=None,
    )


@router.post(
    "/embedding",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Stage 3 — Generate Resume & Job Embeddings",
)
async def generate_embeddings(
    resume_document_id: uuid.UUID = Form(...),
    job_id: uuid.UUID = Form(...),
    job_description: str = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[dict]:
    """Generate semantic vector embeddings using local nomic-embed-text model.

    Both resume and job description embeddings are generated and stored in the database
    for downstream cosine similarity scoring.
    """
    resume_result = await service.generate_resume_embedding(resume_document_id)
    job_result = await service.generate_job_embedding(job_id, job_description)
    return APIResponse[dict](
        success=True,
        message="Embeddings generated successfully.",
        data={"resume": resume_result, "job": job_result},
        errors=None,
    )


@router.post(
    "/match",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SemanticMatchResponse],
    summary="Stage 3 — Semantic Skill Matching",
)
async def match_candidate(
    resume_document_id: uuid.UUID = Form(...),
    job_id: uuid.UUID = Form(...),
    job_description: str = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[SemanticMatchResponse]:
    """Compute cosine similarity score between candidate resume and job description.

    Returns: Match Score (0.0–1.0), Matching Skills, Missing Skills.
    """
    res = await service.match_candidate(resume_document_id, job_id, job_description)
    return APIResponse[SemanticMatchResponse](
        success=True,
        message="Semantic match score computed.",
        data=res,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AiAnalysisResponse],
    summary="Stage 4 — AI Qualitative Evaluation via Llama3",
)
async def analyze_candidate(
    resume_document_id: uuid.UUID = Form(...),
    job_id: uuid.UUID = Form(...),
    job_description: str = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[AiAnalysisResponse]:
    """Evaluate candidate using local Llama3 model.

    Generates: Professional Summary, Strengths, Weaknesses, Risk Factors,
    Hiring Recommendation (Strong Hire/Hire/Maybe/Reject), Culture Fit,
    Technical Fit, Career Progression, Skill Gaps, Upskilling Suggestions.
    """
    res = await service.analyze_candidate(resume_document_id, job_id, job_description)
    return APIResponse[AiAnalysisResponse](
        success=True,
        message="AI candidate evaluation complete.",
        data=res,
        errors=None,
    )


@router.post(
    "/rank",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CandidateRankingResponse],
    summary="Stage 5 — Compute Multi-Dimensional Ranking Scores",
)
async def rank_candidate(
    resume_document_id: uuid.UUID = Form(...),
    job_id: uuid.UUID = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[CandidateRankingResponse]:
    """Compute 10-dimensional scoring for candidate ranking.

    Scores: Overall, Technical, Experience, Education, Project, Certification,
    Communication, Leadership, Culture, Learning (all 0–100).
    """
    res = await service.rank_candidate(resume_document_id, job_id)
    return APIResponse[CandidateRankingResponse](
        success=True,
        message="Candidate ranking scores computed.",
        data=res,
        errors=None,
    )


@router.post(
    "/interview",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[InterviewQuestionsResponse],
    summary="Stage 6 — Generate Targeted Interview Questions",
)
async def generate_interview_questions(
    resume_document_id: uuid.UUID = Form(...),
    job_id: uuid.UUID = Form(...),
    job_description: str = Form(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[InterviewQuestionsResponse]:
    """Generate 15 targeted interview questions via local Llama3.

    Categories: Technical (5), System Design (2), Coding (2), Behavioral (3), HR (3).

    Each question includes: Expected Answer, Evaluation Checklist, and Difficulty Level (Easy/Medium/Hard).
    """
    res = await service.generate_interview_questions(resume_document_id, job_id, job_description)
    return APIResponse[InterviewQuestionsResponse](
        success=True,
        message="Interview questions generated successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "/dashboard/{resume_document_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AiCopilotDashboardView],
    summary="Stage 7 — Candidate AI Hiring Dashboard",
)
async def get_candidate_dashboard(
    resume_document_id: uuid.UUID,
    job_id: uuid.UUID = Query(...),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[AiCopilotDashboardView]:
    """Aggregate all pipeline data into a unified hiring dashboard view.

    Returns: Overall Score, Technical Score, Experience Score, Education Score,
    Project Score, Communication Score, Skill Match %, Missing Skills, Top Skills,
    Strengths, Weaknesses, Career Timeline, AI Recommendation, Interview Questions,
    Risk Analysis, Confidence Score.
    """
    res = await service.get_candidate_dashboard(resume_document_id, job_id)
    return APIResponse[AiCopilotDashboardView](
        success=True,
        message="Candidate hiring dashboard retrieved.",
        data=res,
        errors=None,
    )


@router.get(
    "/job-ranking/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[dict]],
    summary="Get Ranked Candidates for a Job",
)
async def get_job_ranking(
    job_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)] = None,
) -> APIResponse[list[dict]]:
    """Get all candidates ranked by AI scores for a specific job position.

    Returns ranked list with Overall Score, Technical Score, and Experience Score.
    """
    res = await service.get_job_rankings(job_id)
    return APIResponse[list[dict]](
        success=True,
        message=f"Job candidate rankings retrieved. Total candidates: {len(res)}",
        data=res,
        errors=None,
    )


from pydantic import BaseModel

class CopilotRequest(BaseModel):
    tool: str
    job_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    user_input: str | None = None


@router.post(
    "/copilot",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[str],
    summary="Interactive AI Recruiter Copilot",
)
async def run_copilot_tool_route(
    payload: CopilotRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AiCopilotService, Depends(get_ai_copilot_service)],
) -> APIResponse[str]:
    """Run an AI recruiting tool (e.g. summarize, email, skillgap, rank) with real Ollama. Admin and HR only."""
    res = await service.run_copilot_tool(
        tool=payload.tool,
        job_id=payload.job_id,
        candidate_id=payload.candidate_id,
        user_input=payload.user_input,
    )
    return APIResponse[str](
        success=True,
        message="AI copilot output generated successfully.",
        data=res,
        errors=None,
    )
