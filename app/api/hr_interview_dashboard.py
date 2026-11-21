"""HR Interview Dashboard API endpoints for reviewing AI interviews."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Query, status
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.departments import require_admin_or_hr
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.ai_interview import AIInterviewSession, AIInterviewScorecard, AIInterviewResponse, AIInterviewQuestionInstance
from app.models.recruitment import Interview, InterviewRound, Application, Job, Candidate
from app.repositories.recruitment_repository import RecruitmentRepository
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/hr/interviews", tags=["HR Interview Dashboard"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List all company interview sessions with filters",
)
async def list_hr_interviews(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    job_id: Optional[uuid.UUID] = Query(None),
    candidate_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[dict]:
    """List all interview sessions for HR review with filtering and pagination."""
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    
    # Build base query for Interview (traditional) and AIInterviewSession
    # We'll combine both for comprehensive view
    
    # Query traditional interviews
    interview_query = select(Interview).options(
        selectinload(Interview.application).selectinload(Application.job),
        selectinload(Interview.application).selectinload(Application.candidate),
        selectinload(Interview.rounds),
    )
    
    # Query AI interview sessions
    ai_session_query = select(AIInterviewSession).options(
        selectinload(AIInterviewSession.candidate),
        selectinload(AIInterviewSession.job),
        selectinload(AIInterviewSession.scorecard),
    )
    
    if company_id:
        interview_query = interview_query.where(Interview.company_id == company_id)
        ai_session_query = ai_session_query.where(AIInterviewSession.company_id == company_id)
    
    if job_id:
        interview_query = interview_query.where(Interview.application.has(Application.job_id == job_id))
        ai_session_query = ai_session_query.where(AIInterviewSession.job_id == job_id)
    
    if candidate_id:
        interview_query = interview_query.where(Interview.application.has(Application.candidate_id == candidate_id))
        ai_session_query = ai_session_query.where(AIInterviewSession.candidate_id == candidate_id)
    
    if status_filter:
        interview_query = interview_query.where(Interview.status == status_filter.upper())
        ai_session_query = ai_session_query.where(AIInterviewSession.status == status_filter.upper())
    
    if date_from:
        interview_query = interview_query.where(Interview.created_at >= date_from)
        ai_session_query = ai_session_query.where(AIInterviewSession.created_at >= date_from)
    
    if date_to:
        interview_query = interview_query.where(Interview.created_at <= date_to)
        ai_session_query = ai_session_query.where(AIInterviewSession.created_at <= date_to)
    
    # Execute with pagination
    interview_offset = (page - 1) * limit
    ai_offset = (page - 1) * limit
    
    interview_query = interview_query.order_by(Interview.created_at.desc()).limit(limit).offset(interview_offset)
    ai_session_query = ai_session_query.order_by(AIInterviewSession.created_at.desc()).limit(limit).offset(ai_offset)
    
    interviews_res = await db.execute(interview_query)
    ai_sessions_res = await db.execute(ai_session_query)
    
    interviews = interviews_res.scalars().all()
    ai_sessions = ai_sessions_res.scalars().all()
    
    # Get total counts
    total_interviews = await db.execute(select(func.count()).select_from(Interview).where(Interview.company_id == company_id) if company_id else select(func.count()).select_from(Interview))
    total_ai_sessions = await db.execute(select(func.count()).select_from(AIInterviewSession).where(AIInterviewSession.company_id == company_id) if company_id else select(func.count()).select_from(AIInterviewSession))
    
    total = (total_interviews.scalar() or 0) + (total_ai_sessions.scalar() or 0)
    
    # Format response
    items = []
    
    for iv in interviews:
        app_obj = iv.application
        job_obj = app_obj.job if app_obj else None
        cand_obj = app_obj.candidate if app_obj else None
        current_round = iv.rounds[iv.current_round_index] if iv.rounds and iv.current_round_index < len(iv.rounds) else None
        
        items.append({
            "type": "traditional",
            "id": str(iv.id),
            "application_id": str(app_obj.id) if app_obj else None,
            "candidate_name": f"{cand_obj.first_name} {cand_obj.last_name}" if cand_obj else f"{app_obj.first_name} {app_obj.last_name}" if app_obj else "Unknown",
            "candidate_email": cand_obj.email if cand_obj else app_obj.email if app_obj else None,
            "job_title": job_obj.title if job_obj else "Unknown",
            "status": iv.status,
            "current_round": current_round.round_name if current_round else None,
            "current_round_index": iv.current_round_index,
            "total_rounds": len(iv.rounds),
            "created_at": iv.created_at.isoformat() if iv.created_at else None,
            "updated_at": iv.updated_at.isoformat() if iv.updated_at else None,
        })
    
    for ai_sess in ai_sessions:
        cand_obj = ai_sess.candidate
        job_obj = ai_sess.job
        scorecard = ai_sess.scorecard
        
        items.append({
            "type": "ai_video",
            "id": str(ai_sess.id),
            "candidate_id": str(cand_obj.id) if cand_obj else None,
            "candidate_name": f"{cand_obj.first_name} {cand_obj.last_name}" if cand_obj else "Unknown",
            "candidate_email": cand_obj.email if cand_obj else None,
            "job_title": job_obj.title if job_obj else "Unknown",
            "status": ai_sess.status,
            "interview_type": ai_sess.interview_type,
            "current_question_index": ai_sess.current_question_index,
            "total_questions": len(ai_sess.questions),
            "ai_recommendation": scorecard.final_hiring_recommendation if scorecard else None,
            "ai_score": scorecard.scores.get("Technical/Logical", 0) if scorecard and hasattr(scorecard, 'scores') else None,
            "created_at": ai_sess.created_at.isoformat() if ai_sess.created_at else None,
            "updated_at": ai_sess.updated_at.isoformat() if ai_sess.updated_at else None,
        })
    
    return APIResponse[dict](
        success=True,
        message=f"Retrieved {len(items)} interview session(s).",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        },
        errors=None,
    )


@router.get(
    "/{interview_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get detailed interview session for HR review",
)
async def get_hr_interview_detail(
    interview_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Get complete interview details including transcript, scores, and evidence."""
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    
    # Check traditional interview first
    interview_res = await db.execute(
        select(Interview)
        .options(
            selectinload(Interview.application).selectinload(Application.job),
            selectinload(Interview.application).selectinload(Application.candidate),
            selectinload(Interview.rounds),
            selectinload(Interview.schedules),
        )
        .where(Interview.id == interview_id)
    )
    interview = interview_res.scalar_one_or_none()
    
    if interview:
        if company_id and interview.company_id != company_id:
            raise AppException(message="Interview not found.", status_code=status.HTTP_404_NOT_FOUND)
        
        app_obj = interview.application
        job_obj = app_obj.job if app_obj else None
        cand_obj = app_obj.candidate if app_obj else None
        
        rounds_data = []
        for r in interview.rounds:
            rounds_data.append({
                "id": str(r.id),
                "round_name": r.round_name,
                "round_order": r.round_order,
                "status": r.status,
                "feedback": r.feedback,
                "score": r.score,
                "interviewer_name": r.interviewer_name,
                "conducted_at": r.conducted_at.isoformat() if r.conducted_at else None,
            })
        
        schedules_data = []
        for s in interview.schedules:
            schedules_data.append({
                "id": str(s.id),
                "round_id": str(s.round_id),
                "interview_date": s.interview_date.isoformat() if s.interview_date else None,
                "interview_time": s.interview_time.strftime("%H:%M:%S") if s.interview_time else None,
                "mode": s.mode,
                "meeting_url": s.meeting_url,
            })
        
        return APIResponse[dict](
            success=True,
            message="Interview details retrieved.",
            data={
                "type": "traditional",
                "id": str(interview.id),
                "application_id": str(app_obj.id) if app_obj else None,
                "candidate": {
                    "id": str(cand_obj.id) if cand_obj else None,
                    "name": f"{cand_obj.first_name} {cand_obj.last_name}" if cand_obj else f"{app_obj.first_name} {app_obj.last_name}" if app_obj else "Unknown",
                    "email": cand_obj.email if cand_obj else app_obj.email if app_obj else None,
                },
                "job": {
                    "id": str(job_obj.id) if job_obj else None,
                    "title": job_obj.title if job_obj else "Unknown",
                },
                "status": interview.status,
                "current_round_index": interview.current_round_index,
                "rounds": rounds_data,
                "schedules": schedules_data,
                "created_at": interview.created_at.isoformat() if interview.created_at else None,
                "updated_at": interview.updated_at.isoformat() if interview.updated_at else None,
            },
            errors=None,
        )
    
    # Check AI interview session
    ai_session_res = await db.execute(
        select(AIInterviewSession)
        .options(
            selectinload(AIInterviewSession.candidate),
            selectinload(AIInterviewSession.job),
            selectinload(AIInterviewSession.questions),
            selectinload(AIInterviewSession.responses).selectinload(AIInterviewResponse.question),
            selectinload(AIInterviewSession.scorecard),
        )
        .where(AIInterviewSession.id == interview_id)
    )
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    if company_id and ai_session.company_id != company_id:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    cand_obj = ai_session.candidate
    job_obj = ai_session.job
    scorecard = ai_session.scorecard
    
    questions_data = []
    for q in ai_session.questions:
        response = next((r for r in ai_session.responses if r.question_id == q.id), None)
        questions_data.append({
            "id": str(q.id),
            "question_text": q.question_text,
            "question_type": q.question_type,
            "difficulty": q.difficulty,
            "order_index": q.order_index,
            "expected_answer": q.expected_answer,
            "response": {
                "candidate_response": response.candidate_response if response else None,
                "duration_seconds": response.duration_seconds if response else None,
                "score": response.score if response else None,
                "evaluation_feedback": response.evaluation_feedback if response else None,
                "emotion_analysis": response.emotion_analysis if response else None,
                "communication_analysis": response.communication_analysis if response else None,
                "proctoring_flags": response.proctoring_flags if response else None,
            } if response else None,
        })
    
    scorecard_data = None
    if scorecard:
        scorecard_data = {
            "id": str(scorecard.id),
            "final_hiring_recommendation": scorecard.final_hiring_recommendation,
            "overall_justification": scorecard.overall_justification,
            "anti_cheating_report": scorecard.anti_cheating_report,
            "emotion_summary": scorecard.emotion_summary,
            "communication_summary": scorecard.communication_summary,
            "submission_id": str(scorecard.scorecard_submission_id) if scorecard.scorecard_submission_id else None,
        }
    
    return APIResponse[dict](
        success=True,
        message="AI Interview session details retrieved.",
        data={
            "type": "ai_video",
            "id": str(ai_session.id),
            "candidate": {
                "id": str(cand_obj.id) if cand_obj else None,
                "name": f"{cand_obj.first_name} {cand_obj.last_name}" if cand_obj else "Unknown",
                "email": cand_obj.email if cand_obj else None,
            },
            "job": {
                "id": str(job_obj.id) if job_obj else None,
                "title": job_obj.title if job_obj else "Unknown",
            },
            "status": ai_session.status,
            "interview_type": ai_session.interview_type,
            "current_question_index": ai_session.current_question_index,
            "total_questions": len(ai_session.questions),
            "questions": questions_data,
            "scorecard": scorecard_data,
            "created_at": ai_session.created_at.isoformat() if ai_session.created_at else None,
            "updated_at": ai_session.updated_at.isoformat() if ai_session.updated_at else None,
        },
        errors=None,
    )


@router.post(
    "/{interview_id}/feedback",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Add HR feedback and notes to interview",
)
async def add_interview_feedback(
    interview_id: uuid.UUID,
    feedback: str = Form(..., min_length=1),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Add HR feedback/notes to an interview session."""
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(str(user_id_raw)) if user_id_raw else None
    
    # Check traditional interview
    interview_res = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = interview_res.scalar_one_or_none()
    
    if interview:
        if company_id and interview.company_id != company_id:
            raise AppException(message="Interview not found.", status_code=status.HTTP_404_NOT_FOUND)
        
        # Update current round feedback
        if interview.rounds and interview.current_round_index < len(interview.rounds):
            current_round = interview.rounds[interview.current_round_index]
            current_round.feedback = (current_round.feedback or "") + "\n\n[HR Note] " + feedback
            await db.commit()
        
        return APIResponse[dict](
            success=True,
            message="Feedback added to interview.",
            data={"interview_id": str(interview_id)},
            errors=None,
        )
    
    # Check AI interview session
    ai_session_res = await db.execute(select(AIInterviewSession).where(AIInterviewSession.id == interview_id))
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    if company_id and ai_session.company_id != company_id:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    # Add feedback to scorecard or create HR notes
    if ai_session.scorecard:
        ai_session.scorecard.overall_justification += f"\n\n[HR Note by {user_id}] {feedback}"
        await db.commit()
    
    return APIResponse[dict](
        success=True,
        message="Feedback added to AI interview session.",
        data={"interview_id": str(interview_id)},
        errors=None,
    )


@router.post(
    "/{interview_id}/override",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Override AI recommendation with HR decision",
)
async def override_ai_recommendation(
    interview_id: uuid.UUID,
    recommendation: str = Form(..., description="STRONG_HIRE, HIRE, MAYBE, REJECT"),
    reason: str = Form(..., min_length=1),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Override AI hiring recommendation with HR decision."""
    valid_recommendations = {"STRONG_HIRE", "HIRE", "MAYBE", "REJECT"}
    if recommendation not in valid_recommendations:
        raise AppException(
            message=f"Invalid recommendation. Must be one of: {', '.join(valid_recommendations)}",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(str(user_id_raw)) if user_id_raw else None
    
    ai_session_res = await db.execute(
        select(AIInterviewSession).options(selectinload(AIInterviewSession.scorecard))
        .where(AIInterviewSession.id == interview_id)
    )
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        raise AppException(message="AI Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    if company_id and ai_session.company_id != company_id:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    if not ai_session.scorecard:
        raise AppException(message="No AI scorecard exists for this session.", status_code=status.HTTP_400_BAD_REQUEST)
    
    # Store original AI recommendation
    original = ai_session.scorecard.final_hiring_recommendation
    ai_session.scorecard.final_hiring_recommendation = recommendation
    ai_session.scorecard.overall_justification += f"\n\n[HR Override by {user_id}] Changed from {original} to {recommendation}. Reason: {reason}"
    
    # Update application status based on HR decision
    from app.repositories.recruitment_repository import RecruitmentRepository
    from app.models.recruitment import Application
    
    if ai_session.candidate_id:
        app_res = await db.execute(
            select(Application).where(
                Application.candidate_id == ai_session.candidate_id,
                Application.job_id == ai_session.job_id,
            ).order_by(Application.created_at.desc()).limit(1)
        )
        application = app_res.scalar_one_or_none()
        if application:
            status_map = {
                "STRONG_HIRE": "SELECTED",
                "HIRE": "SELECTED",
                "MAYBE": "UNDER_REVIEW",
                "REJECT": "REJECTED",
            }
            new_status = status_map.get(recommendation, "UNDER_REVIEW")
            await db.execute(
                update(Application).where(Application.id == application.id).values(status=new_status)
            )
    
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message=f"AI recommendation overridden to {recommendation}.",
        data={
            "interview_id": str(interview_id),
            "original_recommendation": original,
            "new_recommendation": recommendation,
            "overridden_by": str(user_id),
        },
        errors=None,
    )


@router.post(
    "/{interview_id}/advance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Advance candidate to next stage or schedule another round",
)
async def advance_candidate(
    interview_id: uuid.UUID,
    action: str = Form(..., description="SHORTLIST, SCHEDULE_ROUND, REJECT, HOLD"),
    round_name: Optional[str] = Form(None),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Advance candidate to next stage or schedule another interview round."""
    valid_actions = {"SHORTLIST", "SCHEDULE_ROUND", "REJECT", "HOLD"}
    if action not in valid_actions:
        raise AppException(message=f"Invalid action. Must be one of: {', '.join(valid_actions)}", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    if action == "SCHEDULE_ROUND" and not round_name:
        raise AppException(message="round_name is required for SCHEDULE_ROUND action", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    
    ai_session_res = await db.execute(
        select(AIInterviewSession).where(AIInterviewSession.id == interview_id)
    )
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        raise AppException(message="AI Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    if company_id and ai_session.company_id != company_id:
        raise AppException(message="Interview session not found.", status_code=status.HTTP_404_NOT_FOUND)
    
    # Find the application
    from app.models.recruitment import Application
    app_res = await db.execute(
        select(Application).where(
            Application.candidate_id == ai_session.candidate_id,
            Application.job_id == ai_session.job_id,
        ).order_by(Application.created_at.desc()).limit(1)
    )
    application = app_res.scalar_one_or_none()
    
    if not application:
        raise AppException(message="Application not found for this candidate/job.", status_code=status.HTTP_404_NOT_FOUND)
    
    status_map = {
        "SHORTLIST": "SHORTLISTED",
        "REJECT": "REJECTED",
        "HOLD": "HOLD",
        "SCHEDULE_ROUND": "INTERVIEW_SCHEDULED",
    }
    
    await db.execute(
        update(Application).where(Application.id == application.id).values(status=status_map[action])
    )
    
    if action == "SCHEDULE_ROUND":
        # Create a new interview round
        from app.repositories.recruitment_repository import RecruitmentRepository
        repo = RecruitmentRepository(db)
        
        interview_res = await db.execute(
            select(Interview).where(Interview.application_id == application.id)
        )
        interview = interview_res.scalar_one_or_none()
        
        if interview:
            next_order = len(interview.rounds)
            await repo.create_interview_round(
                interview_id=interview.id,
                round_name=round_name,
                round_order=next_order,
                status="PENDING",
            )
    
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message=f"Candidate advanced with action: {action}",
        data={
            "application_id": str(application.id),
            "new_status": status_map[action],
            "action": action,
        },
        errors=None,
    )