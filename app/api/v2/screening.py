"""AI Screening API v2 — Auto-screen candidates with SHORTLIST/REVIEW/REJECT decisions."""

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
from app.agents.screening_agent import ScreeningAgent
from app.llm.client import get_llm_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/screening",
    tags=["AI Screening Agent v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class ScreenRequest(BaseModel):
    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    model: str | None = None
    auto_apply_decision: bool = Field(
        False,
        description="Auto-update application status based on screening decision"
    )


class BatchScreenRequest(BaseModel):
    job_id: uuid.UUID
    resume_document_ids: list[uuid.UUID] = Field(..., max_length=100)
    model: str | None = None
    auto_apply_decisions: bool = False


@router.post(
    "/screen",
    response_model=APIResponse[dict],
    summary="AI-screen a single candidate",
    description="""
Auto-screen a candidate for a job with a three-tier decision:

- **SHORTLIST** — Strong match above configured threshold  
- **REVIEW** — Borderline, requires human review  
- **REJECT** — Clear mismatch below rejection threshold  

Generates: strengths, weaknesses, missing skills, risk analysis, red flags,
green flags, HR notes, and suggested interview questions.
""",
)
async def screen_candidate(
    body: ScreenRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Screen a single candidate and return detailed analysis."""
    from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore, AIScreeningResult
    from app.models.recruitment import Job, Application

    # Load resume document
    doc_res = await db.execute(
        select(AIResumeDocument).where(AIResumeDocument.id == body.resume_document_id)
    )
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Resume document not found")
    if doc.parse_status != "COMPLETED":
        raise HTTPException(status_code=422, detail="Resume not yet parsed")

    # Load job
    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get pre-computed match score if available
    score_res = await db.execute(
        select(CandidateMatchScore)
        .where(
            CandidateMatchScore.resume_document_id == body.resume_document_id,
            CandidateMatchScore.job_id == body.job_id,
        )
        .order_by(CandidateMatchScore.created_at.desc())
        .limit(1)
    )
    match_score_rec = score_res.scalar_one_or_none()
    match_score = match_score_rec.overall_match_score if match_score_rec else 0.5

    # Build texts
    resume_text = doc.raw_text or ""
    if not resume_text:
        parsed = doc.parsed_data or {}
        resume_text = " ".join(filter(None, [
            parsed.get("summary", ""),
            parsed.get("name", ""),
            " ".join(parsed.get("skills", {}).get("programming_languages", [])),
        ]))

    jd_text = job.job_description + "\n" + (job.requirements or "")

    # Run screening agent
    agent = ScreeningAgent(llm_client=get_llm_client())
    result = await agent.screen(
        resume_text=resume_text,
        jd_text=jd_text,
        match_score=match_score,
        model=body.model,
    )

    # Store screening result
    screening_rec = AIScreeningResult(
        application_id=doc.application_id or uuid.uuid4(),  # Fallback if no application
        resume_document_id=body.resume_document_id,
        job_id=body.job_id,
        decision=result.decision,
        confidence=result.confidence,
        auto_action_taken=result.auto_shortlisted or result.auto_rejected,
        strengths=result.strengths,
        weaknesses=result.weaknesses,
        missing_skills=result.missing_skills,
        risk_analysis=result.risk_analysis,
        red_flags=result.red_flags,
        green_flags=result.green_flags,
        hiring_recommendation=result.hiring_recommendation,
        hr_notes=result.hr_notes,
        questions_to_ask=result.questions_to_ask,
        model_used=body.model,
    )
    db.add(screening_rec)

    # Auto-apply decision if requested and application exists
    if body.auto_apply_decision and doc.application_id and (result.auto_shortlisted or result.auto_rejected):
        from sqlalchemy import update
        new_status = "SHORTLISTED" if result.auto_shortlisted else "REJECTED"
        await db.execute(
            update(Application)
            .where(Application.id == doc.application_id)
            .values(status=new_status)
        )
        logger.info("Auto-applied status %s to application %s", new_status, doc.application_id)

    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Screening complete. Decision: {result.decision}",
        data={
            "screening_id": str(screening_rec.id),
            "resume_document_id": str(body.resume_document_id),
            "job_id": str(body.job_id),
            "match_score_used": match_score,
            **result.to_dict(),
        },
        errors=None,
    )


@router.post(
    "/batch-screen",
    response_model=APIResponse[dict],
    summary="Batch screen multiple candidates for a job",
)
async def batch_screen_candidates(
    body: BatchScreenRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Screen multiple candidates concurrently for a job."""
    from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
    from app.models.recruitment import Job

    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    jd_text = job.job_description + "\n" + (job.requirements or "")

    docs_res = await db.execute(
        select(AIResumeDocument).where(
            AIResumeDocument.id.in_(body.resume_document_ids),
            AIResumeDocument.parse_status == "COMPLETED",
        )
    )
    docs = docs_res.scalars().all()

    if not docs:
        raise HTTPException(status_code=422, detail="No completed resumes found")

    # Get pre-computed scores
    score_map: dict[str, float] = {}
    scores_res = await db.execute(
        select(CandidateMatchScore).where(
            CandidateMatchScore.resume_document_id.in_([d.id for d in docs]),
            CandidateMatchScore.job_id == body.job_id,
        )
    )
    for s in scores_res.scalars().all():
        score_map[str(s.resume_document_id)] = s.overall_match_score

    candidates_input = [
        {
            "resume_text": doc.raw_text or "",
            "match_score": score_map.get(str(doc.id), 0.5),
        }
        for doc in docs
    ]

    agent = ScreeningAgent(llm_client=get_llm_client())
    results = await agent.screen_batch(candidates_input, jd_text, model=body.model)

    output = []
    shortlisted, rejected, review = 0, 0, 0
    for doc, result in zip(docs, results):
        if result.decision == "SHORTLIST":
            shortlisted += 1
        elif result.decision == "REJECT":
            rejected += 1
        else:
            review += 1
        output.append({
            "resume_document_id": str(doc.id),
            "candidate_name": doc.candidate_name,
            "decision": result.decision,
            "confidence": round(result.confidence, 4),
            "auto_shortlisted": result.auto_shortlisted,
            "auto_rejected": result.auto_rejected,
            "hr_notes": result.hr_notes,
        })

    return APIResponse[dict](
        success=True,
        message=f"Batch screening complete: {shortlisted} shortlisted, {rejected} rejected, {review} for review.",
        data={
            "job_id": str(body.job_id),
            "total": len(output),
            "shortlisted": shortlisted,
            "rejected": rejected,
            "review": review,
            "results": output,
        },
        errors=None,
    )


@router.get(
    "/history/{application_id}",
    response_model=APIResponse[dict],
    summary="Get screening history for an application",
)
async def get_screening_history(
    application_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve all screening results for an application."""
    from app.models.ai_recruitment import AIScreeningResult

    result = await db.execute(
        select(AIScreeningResult)
        .where(AIScreeningResult.application_id == application_id)
        .order_by(AIScreeningResult.created_at.desc())
    )
    records = result.scalars().all()

    return APIResponse[dict](
        success=True,
        message=f"Found {len(records)} screening record(s).",
        data={
            "application_id": str(application_id),
            "total": len(records),
            "records": [
                {
                    "id": str(r.id),
                    "decision": r.decision,
                    "confidence": r.confidence,
                    "auto_action_taken": r.auto_action_taken,
                    "hiring_recommendation": r.hiring_recommendation,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ],
        },
        errors=None,
    )
