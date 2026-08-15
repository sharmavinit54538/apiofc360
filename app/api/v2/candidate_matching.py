"""Candidate Matching API v2 — JD-Resume match scoring endpoints."""

from __future__ import annotations
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.agents.candidate_matcher import CandidateMatcherAgent
from app.llm.client import get_llm_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/matching",
    tags=["AI Candidate Matching v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class MatchRequest(BaseModel):
    resume_document_id: uuid.UUID = Field(..., description="Parsed resume document UUID")
    job_id: uuid.UUID = Field(..., description="Job UUID")
    model: str | None = Field(None, description="Ollama model override")


class BatchMatchRequest(BaseModel):
    job_id: uuid.UUID
    resume_document_ids: list[uuid.UUID] = Field(..., max_length=100)
    model: str | None = None


@router.post(
    "/score",
    response_model=APIResponse[dict],
    summary="Compute AI match score between resume and job",
)
async def compute_match_score(
    body: MatchRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Compute a multi-dimensional match score (10 dimensions).

    Requires a parsed resume document and a job ID.
    Returns scores, explanations, skill gaps, and hiring recommendation.
    """
    from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
    from app.models.recruitment import Job
    from sqlalchemy import update

    # Load resume document
    doc_res = await db.execute(
        select(AIResumeDocument).where(AIResumeDocument.id == body.resume_document_id)
    )
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Resume document not found")
    if doc.parse_status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Resume not yet parsed. Run /parse first.")

    # Load job
    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Extract texts
    parsed = doc.parsed_data or {}
    resume_text = doc.raw_text or ""
    if not resume_text and parsed:
        # Reconstruct summary from parsed data
        parts = [parsed.get("summary") or "", parsed.get("name") or ""]
        for exp in (parsed.get("experience") or []):
            parts.append(f"{exp.get('designation', '')} at {exp.get('company', '')}")
        resume_text = " ".join(p for p in parts if p)

    jd_text = job.job_description
    if job.requirements:
        jd_text += "\n\nRequirements:\n" + job.requirements
    if job.responsibilities:
        jd_text += "\n\nResponsibilities:\n" + job.responsibilities

    # Run matcher
    agent = CandidateMatcherAgent(llm_client=get_llm_client())
    result = await agent.match(
        resume_text=resume_text,
        jd_text=jd_text,
        model=body.model,
        candidate_metadata={
            "expected_salary": parsed.get("expected_salary"),
            "notice_period": parsed.get("notice_period"),
            "location": parsed.get("address"),
        },
    )

    # Store in DB
    score_record = CandidateMatchScore(
        resume_document_id=body.resume_document_id,
        job_id=body.job_id,
        candidate_id=doc.candidate_id,
        overall_match_score=result.overall_match_score,
        skill_match_score=result.skill_match_score,
        experience_match_score=result.experience_match_score,
        education_match_score=result.education_match_score,
        domain_match_score=result.domain_match_score,
        industry_match_score=result.industry_match_score,
        location_match_score=result.location_match_score,
        salary_match_score=result.salary_match_score,
        availability_score=result.availability_score,
        ai_confidence_score=result.ai_confidence_score,
        matching_skills=result.matching_skills,
        missing_skills=result.missing_skills,
        extra_skills=result.extra_skills,
        analysis_data=result.to_dict(),
        recommendation=result.recommendation,
        model_used=body.model,
        computed_by=uuid.UUID(claims["sub"]) if claims else None,
    )
    db.add(score_record)
    await db.commit()

    return APIResponse[dict](
        success=True,
        message="Match score computed successfully.",
        data={
            "match_score_id": str(score_record.id),
            **result.to_dict(),
        },
        errors=None,
    )


@router.post(
    "/batch-score",
    response_model=APIResponse[dict],
    summary="Batch match multiple resumes against a single job",
)
async def batch_match_scores(
    body: BatchMatchRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Match multiple candidate resumes against a job concurrently (max 100)."""
    from app.models.ai_recruitment import AIResumeDocument
    from app.models.recruitment import Job

    # Load job
    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    jd_text = job.job_description + "\n" + (job.requirements or "")

    # Load all resume documents
    docs_res = await db.execute(
        select(AIResumeDocument).where(
            AIResumeDocument.id.in_(body.resume_document_ids),
            AIResumeDocument.parse_status == "COMPLETED",
        )
    )
    docs = docs_res.scalars().all()

    candidates = [
        {
            "resume_text": d.raw_text or "",
            "metadata": {
                "expected_salary": (d.parsed_data or {}).get("expected_salary"),
                "notice_period": (d.parsed_data or {}).get("notice_period"),
            },
        }
        for d in docs
    ]

    agent = CandidateMatcherAgent(llm_client=get_llm_client())
    results = await agent.match_batch(candidates, jd_text, model=body.model)

    batch_results = [
        {
            "resume_document_id": str(doc.id),
            "candidate_name": doc.candidate_name,
            **result.to_dict(),
        }
        for doc, result in zip(docs, results)
    ]

    # Sort by overall score
    batch_results.sort(key=lambda r: r["overall_match_score"], reverse=True)

    return APIResponse[dict](
        success=True,
        message=f"Batch matching completed for {len(docs)} candidates.",
        data={"job_id": str(body.job_id), "results": batch_results, "total": len(batch_results)},
        errors=None,
    )


@router.get(
    "/history/{resume_document_id}",
    response_model=APIResponse[dict],
    summary="Get match score history for a resume",
)
async def get_match_history(
    resume_document_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve all match scores for a given resume document."""
    from app.models.ai_recruitment import CandidateMatchScore

    result = await db.execute(
        select(CandidateMatchScore)
        .where(CandidateMatchScore.resume_document_id == resume_document_id)
        .order_by(CandidateMatchScore.created_at.desc())
    )
    scores = result.scalars().all()

    return APIResponse[dict](
        success=True,
        message=f"Found {len(scores)} match score records.",
        data={
            "resume_document_id": str(resume_document_id),
            "total": len(scores),
            "scores": [
                {
                    "id": str(s.id),
                    "job_id": str(s.job_id),
                    "overall_match_score": s.overall_match_score,
                    "recommendation": s.recommendation,
                    "created_at": s.created_at.isoformat(),
                }
                for s in scores
            ],
        },
        errors=None,
    )
