"""API v2 router for the AI Behavioural Interview Generator Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.behavioural_service import BehaviouralInterviewService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/behavioural", tags=["AI Behavioural Interview v2"])


# Requests
class CreateSessionRequest(BaseModel):
    company_id: uuid.UUID
    role: str
    experience_years: int = Field(..., ge=0)
    seniority: str = Field(..., description="JUNIOR | MID | SENIOR | LEAD")
    company_culture: str
    model: Optional[str] = None

class RespondQuestionRequest(BaseModel):
    response_text: str = Field(..., min_length=1)
    model: Optional[str] = None


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create custom behavioral interview session",
)
async def create_session(
    body: CreateSessionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generates a sequence of target STAR/Leadership questions matching candidate level and culture."""
    service = BehaviouralInterviewService(db)
    session = await service.create_interview_session(
        company_id=body.company_id,
        role=body.role,
        experience_years=body.experience_years,
        seniority=body.seniority,
        company_culture=body.company_culture,
        model=body.model
    )

    # Re-query session questions
    from sqlalchemy import select
    from app.models.behavioural_interview import BehaviouralInterviewQuestion
    stmt = select(BehaviouralInterviewQuestion).where(BehaviouralInterviewQuestion.session_id == session.id)
    res = await db.execute(stmt)
    questions = res.scalars().all()

    return APIResponse[dict](
        success=True,
        message="Behavioural interview session created.",
        data={
            "session_id": str(session.id),
            "role": session.role,
            "questions_count": len(questions),
            "questions": [
                {
                    "question_id": str(q.id),
                    "dimension": q.dimension,
                    "question_text": q.question_text,
                }
                for q in questions
            ]
        },
        errors=None
    )


@router.post(
    "/questions/{question_id}/respond",
    response_model=APIResponse[dict],
    summary="Submit candidate response and evaluate STAR metrics",
)
async def respond_question(
    question_id: uuid.UUID,
    body: RespondQuestionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Saves candidate answer transcript and runs local LLM evaluation rating and feedback."""
    service = BehaviouralInterviewService(db)
    try:
        q = await service.evaluate_question_response(
            question_id=question_id,
            candidate_response=body.response_text,
            model=body.model
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Response evaluated.",
        data={
            "question_id": str(q.id),
            "evaluation_score": q.evaluation_score,
            "evaluation_feedback": q.evaluation_feedback,
        },
        errors=None
    )
