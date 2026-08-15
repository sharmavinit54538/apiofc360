"""AI Resume Ranking API v2 — Rank candidates for a job."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.agents.resume_ranker import ResumeRankerAgent
from app.llm.client import get_llm_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/ranking",
    tags=["AI Resume Ranking v2"],
    dependencies=[Depends(require_admin_or_manager)],
)

VALID_TOP_N = {10, 25, 50, 100}


class RankCandidatesRequest(BaseModel):
    job_id: uuid.UUID
    resume_document_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=200)
    top_n: int = Field(50, description="Number of top candidates to return (10|25|50|100)")
    model: str | None = None


@router.post(
    "/rank",
    response_model=APIResponse[dict],
    summary="AI-rank candidates for a job",
    description="""
Rank a batch of candidates for a specific job using 10 AI scoring dimensions:

- **Skills Fit** (25%) — how well technical skills match JD requirements  
- **Experience Relevance** (20%) — years and domain relevance  
- **Semantic Similarity** (15%) — embedding-based JD-resume alignment  
- **Projects** (12%) — quality and relevance of portfolio  
- **Culture Fit** (10%) — signals for team and company fit  
- **Education** (8%) — degree level and field relevance  
- **Career Growth** (5%) — progression trajectory  
- **Stability** (3%) — average job tenure  
- **Leadership** (1%) — leadership indicators  
- **Certifications** (1%) — professional credentials  

Returns Top 10 / 25 / 50 / 100 ranked list with per-dimension explanations.
""",
)
async def rank_candidates(
    body: RankCandidatesRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Rank candidates for a job and return ordered list."""
    from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
    from app.models.recruitment import Job

    # Validate top_n
    top_n = body.top_n if body.top_n in VALID_TOP_N else 50

    # Load job
    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    jd_text = job.job_description + "\n" + (job.requirements or "") + "\n" + (job.responsibilities or "")

    # Load resume documents
    docs_res = await db.execute(
        select(AIResumeDocument).where(
            AIResumeDocument.id.in_(body.resume_document_ids),
            AIResumeDocument.parse_status == "COMPLETED",
        )
    )
    docs = docs_res.scalars().all()

    if not docs:
        raise HTTPException(status_code=422, detail="No completed resume documents found.")

    # Load any pre-computed match scores to blend in
    score_map: dict[str, float] = {}
    scores_res = await db.execute(
        select(CandidateMatchScore).where(
            CandidateMatchScore.resume_document_id.in_([d.id for d in docs]),
            CandidateMatchScore.job_id == body.job_id,
        )
    )
    for s in scores_res.scalars().all():
        score_map[str(s.resume_document_id)] = s.overall_match_score

    # Build candidate input
    candidates = []
    for doc in docs:
        parsed = doc.parsed_data or {}
        resume_text = doc.raw_text or ""
        if not resume_text and parsed.get("summary"):
            resume_text = parsed["summary"]

        candidates.append({
            "id": str(doc.id),
            "name": doc.candidate_name or (parsed.get("name") or "Unknown"),
            "resume_text": resume_text,
            "existing_match_score": score_map.get(str(doc.id)),
        })

    # Run ranker
    agent = ResumeRankerAgent(llm_client=get_llm_client())
    result = await agent.rank(
        candidates=candidates,
        jd_text=jd_text,
        job_id=str(body.job_id),
        top_n=top_n,
        model=body.model,
    )

    return APIResponse[dict](
        success=True,
        message=f"Ranking complete. Top {top_n} candidates returned.",
        data=result.to_dict(),
        errors=None,
    )


@router.get(
    "/top/{job_id}",
    response_model=APIResponse[dict],
    summary="Get pre-ranked candidates for a job from stored scores",
)
async def get_ranked_candidates(
    job_id: uuid.UUID,
    top_n: int = Query(10, description="Number of top candidates (10|25|50|100)"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve ranked candidates using stored match scores (no new LLM call)."""
    from app.models.ai_recruitment import CandidateMatchScore, AIResumeDocument

    top_n = top_n if top_n in VALID_TOP_N else 10

    result = await db.execute(
        select(CandidateMatchScore)
        .where(CandidateMatchScore.job_id == job_id)
        .order_by(CandidateMatchScore.overall_match_score.desc())
        .limit(top_n)
    )
    scores = result.scalars().all()

    ranked = []
    for rank, score in enumerate(scores, start=1):
        doc_res = await db.execute(
            select(AIResumeDocument).where(AIResumeDocument.id == score.resume_document_id)
        )
        doc = doc_res.scalar_one_or_none()
        ranked.append({
            "rank": rank,
            "resume_document_id": str(score.resume_document_id),
            "candidate_name": doc.candidate_name if doc else None,
            "candidate_id": str(score.candidate_id) if score.candidate_id else None,
            "overall_match_score": round(score.overall_match_score, 4),
            "skill_match_score": round(score.skill_match_score, 4),
            "experience_match_score": round(score.experience_match_score, 4),
            "recommendation": score.recommendation,
        })

    return APIResponse[dict](
        success=True,
        message=f"Top {top_n} candidates retrieved from stored scores.",
        data={
            "job_id": str(job_id),
            "top_n": top_n,
            "total": len(ranked),
            "ranked_candidates": ranked,
        },
        errors=None,
    )
