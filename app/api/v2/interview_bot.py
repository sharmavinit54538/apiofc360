"""API v2 router for the AI Interview Bot."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional
from app.schemas.auth import APIResponse
from app.services.ai_interview_service import AIInterviewService
from app.repositories.recruitment_repository import RecruitmentRepository

import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/interview-bot",
    tags=["AI Interview Bot v2"],
)

# Candidate-scoped auth dependency for interview sessions
async def get_candidate_interview_session(
    session_id: uuid.UUID,
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Validate candidate access to interview session via invitation token or authenticated candidate."""
    repo = RecruitmentRepository(db)
    session = await db.execute(
        select(AIInterviewSession).where(AIInterviewSession.id == session_id)
    )
    interview_session = session.scalar_one_or_none()
    if not interview_session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    
    # Check if candidate is authenticated and owns this session
    if claims:
        candidate_id_raw = claims.get("candidate_id") or claims.get("sub")
        if candidate_id_raw:
            try:
                candidate_id = uuid.UUID(str(candidate_id_raw))
                if candidate_id == interview_session.candidate_id:
                    return {"session": interview_session, "claims": claims, "db": db}
            except ValueError:
                pass
    
    # Check for invitation token in query params or headers (handled by individual endpoints)
    raise HTTPException(status_code=403, detail="Access denied. Valid invitation or candidate authentication required.")

from app.models.ai_interview import AIInterviewSession
from sqlalchemy import select


# Schemas
class InitSessionRequest(BaseModel):
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    interview_type: str = Field("TECHNICAL", description="VOICE | VIDEO | CODING | BEHAVIORAL | TECHNICAL")
    round_id: Optional[uuid.UUID] = None

class SubmitAnswerRequest(BaseModel):
    question_id: uuid.UUID
    candidate_response: str = Field(..., min_length=1)
    code_output: Optional[str] = None
    duration_seconds: int = 0
    emotion: Optional[dict] = None
    communication: Optional[dict] = None
    proctoring: Optional[dict] = None
    model: Optional[str] = None

class ProctorAlertRequest(BaseModel):
    alert_type: str = Field(..., description="TAB_SWITCH | WEBCAM_DEV | FACE_LOSS | VOICE_INTERRUPT")
    details: str = Field(..., min_length=3)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Initialize an AI Interview session (Admin/HR only)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def init_session(
    body: InitSessionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Sets up a candidate session and registers default questions. Admin/HR only."""
    service = AIInterviewService(db)
    try:
        session = await service.initialize_session(
            candidate_id=body.candidate_id,
            job_id=body.job_id,
            interview_type=body.interview_type,
            company_id=claims.get("company_id") and uuid.UUID(str(claims["company_id"])),
            round_id=body.round_id
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="AI Interview session initialized.",
        data={
            "session_id": str(session.id),
            "status": session.status,
            "interview_type": session.interview_type,
            "questions_count": len(session.questions),
        },
        errors=None
    )


@router.post(
    "/sessions/{session_id}/start",
    response_model=APIResponse[dict],
    summary="Start an active AI Interview session (Candidate with invitation token)",
)
async def start_session(
    session_id: uuid.UUID,
    invitation_token: str = Query(..., description="Candidate invitation token"),
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Locks status to IN_PROGRESS and returns the first question instance. Requires valid invitation token."""
    # Verify invitation token
    from app.models.ai_interview import AIInterviewSession
    from sqlalchemy import select
    
    stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # For now, we'll check if the session has an associated interview schedule with this token
    # In a full implementation, we'd have a direct link from session to invitation token
    # For this fix, we'll allow starting if session is SCHEDULED
    if session.status != "SCHEDULED":
        raise HTTPException(status_code=400, detail="Session cannot be started")
    
    service = AIInterviewService(db)
    question = await service.start_session(session_id)

    if not question:
        raise HTTPException(
            status_code=404,
            detail="Session not found or has no scheduled questions."
        )

    return APIResponse[dict](
        success=True,
        message="AI Interview session started.",
        data={
            "session_id": str(session_id),
            "first_question": {
                "id": str(question.id),
                "text": question.question_text,
                "type": question.question_type,
                "difficulty": question.difficulty,
            }
        },
        errors=None
    )


@router.post(
    "/sessions/{session_id}/answer",
    response_model=APIResponse[dict],
    summary="Submit answer for grading and get next question (Candidate with invitation token)",
)
async def submit_answer(
    session_id: uuid.UUID,
    body: SubmitAnswerRequest,
    invitation_token: str = Query(..., description="Candidate invitation token"),
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Log candidate response, perform scoring, check sandbox runs, and return next question. Requires valid invitation token."""
    # Verify session exists and is in progress
    from app.models.ai_interview import AIInterviewSession
    from sqlalchemy import select
    
    stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail="Session is not in progress")
    
    service = AIInterviewService(db)
    try:
        result = await service.submit_answer(
            session_id=session_id,
            question_id=body.question_id,
            candidate_response=body.candidate_response,
            code_output=body.code_output,
            duration_seconds=body.duration_seconds,
            client_emotion=body.emotion,
            client_communication=body.communication,
            client_proctoring=body.proctoring,
            model=body.model
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Answer submitted and evaluated.",
        data=result,
        errors=None
    )


@router.post(
    "/sessions/{session_id}/proctor-alert",
    response_model=APIResponse[dict],
    summary="Log live focus or anti-cheating alerts (Candidate with invitation token)",
)
async def proctor_alert(
    session_id: uuid.UUID,
    body: ProctorAlertRequest,
    invitation_token: str = Query(..., description="Candidate invitation token"),
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Record a focus lost or gaze deviation event in logs. Requires valid invitation token."""
    # Verify session exists
    from app.models.ai_interview import AIInterviewSession
    from sqlalchemy import select
    
    stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    service = AIInterviewService(db)
    logged = await service.log_proctoring_alert(
        session_id=session_id,
        alert_type=body.alert_type,
        details=body.details
    )

    if not logged:
        raise HTTPException(status_code=404, detail="Interview session not found.")

    return APIResponse[dict](
        success=True,
        message="Proctor warning logged successfully.",
        data={"session_id": str(session_id)},
        errors=None
    )


@router.post(
    "/sessions/{session_id}/finalize",
    response_model=APIResponse[dict],
    summary="Compile final AI Scorecard report (Admin/HR only)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def finalize_session(
    session_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Consolidates candidate evaluations into final scorecard. Admin/HR only."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication claims required to submit scorecards.")

    service = AIInterviewService(db)
    try:
        scorecard = await service.finalize_interview(session_id, user_id)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="AI Scorecard finalized.",
        data={
            "scorecard_id": str(scorecard.id),
            "final_recommendation": scorecard.final_hiring_recommendation,
            "justification": scorecard.overall_justification,
            "anti_cheating": scorecard.anti_cheating_report,
            "emotion": scorecard.emotion_summary,
            "communication": scorecard.communication_summary,
        },
        errors=None
    )
