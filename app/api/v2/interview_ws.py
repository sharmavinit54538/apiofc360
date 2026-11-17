"""WebSocket endpoints for real-time AI Video Interview."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status, WebSocketException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims_optional
from app.repositories.recruitment_repository import RecruitmentRepository
from app.services.ai_interview_service import AIInterviewService
from app.models.ai_interview import AIInterviewSession
from app.models.recruitment import InterviewInvitation

router = APIRouter(prefix="/interview-ws", tags=["AI Interview WebSocket"])


class ConnectionManager:
    """Manage active WebSocket connections for interview sessions."""

    def __init__(self):
        self.active_connections: dict[uuid.UUID, WebSocket] = {}

    async def connect(self, session_id: uuid.UUID, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: uuid.UUID):
        self.active_connections.pop(session_id, None)

    async def send_json(self, session_id: uuid.UUID, data: dict):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(data)

    async def send_bytes(self, session_id: uuid.UUID, data: bytes):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_bytes(data)


manager = ConnectionManager()


async def get_interview_session_ws(
    token: str = Query(..., description="Interview invitation token"),
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> AIInterviewSession:
    """Validate interview invitation token and return session."""
    repo = RecruitmentRepository(db)
    from app.models.recruitment import InterviewInvitation
    
    invitation = await db.execute(
        select(InterviewInvitation).where(InterviewInvitation.token == token)
    )
    invitation = invitation.scalar_one_or_none()
    
    if not invitation:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid invitation token")
    
    if invitation.status in ("EXPIRED", "COMPLETED", "CANCELLED"):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=f"Invitation is {invitation.status.lower()}")
    
    if invitation.expires_at and invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = "EXPIRED"
        await db.commit()
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invitation has expired")
    
    # Get or create AI interview session
    ai_session_res = await db.execute(
        select(AIInterviewSession).where(AIInterviewSession.interview_round_id == invitation.round_id)
    )
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        # Create new AI interview session
        ai_service = AIInterviewService(db)
        ai_session = await ai_service.initialize_session(
            candidate_id=invitation.candidate_id,
            job_id=invitation.interview.job_id if invitation.interview else None,
            interview_type="VIDEO",
            company_id=invitation.company_id,
            round_id=invitation.round_id,
        )
    
    return ai_session


@router.websocket("/session/{token}")
async def interview_websocket(
    websocket: WebSocket,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    """WebSocket endpoint for real-time AI video interview.
    
    Client flow:
    1. Connect with invitation token
    2. Receive session info and first question
    3. Send audio/video chunks
    4. Receive AI responses and next questions
    5. Handle reconnection within grace period
    """
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models.recruitment import InterviewInvitation
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Validate token
    repo = RecruitmentRepository(db)
    invitation_res = await db.execute(
        select(InterviewInvitation).where(InterviewInvitation.token == token)
    )
    invitation = invitation_res.scalar_one_or_none()
    
    if not invitation:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid invitation token")
        return
    
    if invitation.status in ("EXPIRED", "COMPLETED", "CANCELLED"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=f"Invitation is {invitation.status.lower()}")
        return
    
    if invitation.expires_at and invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = "EXPIRED"
        await db.commit()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invitation has expired")
        return
    
    # Get or create AI interview session
    ai_session_res = await db.execute(
        select(AIInterviewSession).where(AIInterviewSession.interview_round_id == invitation.round_id)
    )
    ai_session = ai_session_res.scalar_one_or_none()
    
    if not ai_session:
        from app.services.ai_interview_service import AIInterviewService
        ai_service = AIInterviewService(db)
        ai_session = await ai_service.initialize_session(
            candidate_id=invitation.candidate_id,
            job_id=invitation.interview.job_id if invitation.interview else None,
            interview_type="VIDEO",
            company_id=invitation.company_id,
            round_id=invitation.round_id,
        )
    
    session_id = ai_session.id
    
    # Handle reconnection
    if invitation.status == "STARTED" and session_id in manager.active_connections:
        # Close old connection
        old_ws = manager.active_connections[session_id]
        try:
            await old_ws.close(code=status.WS_1000_NORMAL_CLOSURE, reason="Reconnected")
        except Exception:
            pass
        invitation.reconnect_count += 1
        if invitation.reconnect_count > invitation.max_reconnects:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Max reconnection attempts exceeded")
            return
    elif invitation.status == "SENT":
        invitation.status = "OPENED"
        invitation.opened_at = datetime.now(timezone.utc)
    
    invitation.status = "STARTED"
    invitation.started_at = datetime.now(timezone.utc)
    invitation.grace_period_ends_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await db.commit()
    
    # Connect
    await manager.connect(session_id, websocket)
    
    try:
        # Send initial session info
        question = None
        if ai_session.current_question_index < len(ai_session.questions):
            question = ai_session.questions[ai_session.current_question_index]
        
        await websocket.send_json({
            "type": "session_started",
            "session_id": str(session_id),
            "invitation_id": str(invitation.id),
            "round_name": invitation.round.round_name if invitation.round else "Interview",
            "job_title": invitation.interview.job.title if invitation.interview and invitation.interview.job else "Position",
            "company_name": invitation.interview.job.company.name if invitation.interview and invitation.interview.job and invitation.interview.job.company else "Company",
            "total_questions": len(ai_session.questions),
            "current_question_index": ai_session.current_question_index,
            "first_question": {
                "id": str(question.id),
                "text": question.question_text,
                "type": question.question_type,
                "difficulty": question.difficulty,
            } if question else None,
            "grace_period_ends_at": invitation.grace_period_ends_at.isoformat() if invitation.grace_period_ends_at else None,
        })
        
        # Start session in AI service
        from app.services.ai_interview_service import AIInterviewService
        ai_service = AIInterviewService(db)
        await ai_service.start_session(session_id)
        
        # Message loop
        while True:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                continue
            
            msg_type = message.get("type")
            
            if msg_type == "answer":
                # Handle candidate answer
                question_id = uuid.UUID(message.get("question_id"))
                candidate_response = message.get("candidate_response", "")
                duration_seconds = message.get("duration_seconds", 0)
                client_emotion = message.get("emotion")
                client_communication = message.get("communication")
                client_proctoring = message.get("proctoring")
                
                try:
                    result = await ai_service.submit_answer(
                        session_id=session_id,
                        question_id=question_id,
                        candidate_response=candidate_response,
                        duration_seconds=duration_seconds,
                        client_emotion=client_emotion,
                        client_communication=client_communication,
                        client_proctoring=client_proctoring,
                    )
                    
                    await websocket.send_json({
                        "type": "answer_evaluated",
                        "question_id": str(question_id),
                        "score_logged": result.get("score_logged"),
                        "evaluation_status": result.get("evaluation_status"),
                        "evaluation": result.get("evaluation"),
                        "next_question": result.get("next_question"),
                        "session_status": result.get("session_status"),
                    })
                    
                    if result.get("session_status") == "COMPLETED":
                        invitation.status = "COMPLETED"
                        invitation.completed_at = datetime.now(timezone.utc)
                        await db.commit()
                        
                        # Generate final scorecard
                        scorecard = await ai_service.finalize_interview(
                            session_id=session_id,
                            submitted_by_user_id=invitation.candidate_id,  # Will be overridden by HR later
                        )
                        
                        await websocket.send_json({
                            "type": "session_completed",
                            "scorecard_id": str(scorecard.id),
                            "final_recommendation": scorecard.final_hiring_recommendation,
                            "justification": scorecard.overall_justification,
                        })
                        break
                        
                except Exception as e:
                    logger.error(f"Answer evaluation failed: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Failed to evaluate answer. Please try again.",
                    })
                    
            elif msg_type == "proctor_alert":
                # Handle proctoring alerts
                alert_type = message.get("alert_type")
                details = message.get("details", "")
                await ai_service.log_proctoring_alert(session_id, alert_type, details)
                await websocket.send_json({"type": "proctor_ack", "alert_type": alert_type})
                
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                
            elif msg_type == "reconnect":
                # Handle explicit reconnection
                invitation.reconnect_count += 1
                invitation.grace_period_ends_at = datetime.now(timezone.utc) + timedelta(minutes=30)
                await db.commit()
                await websocket.send_json({"type": "reconnected", "grace_period_ends_at": invitation.grace_period_ends_at.isoformat()})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception(f"Interview WebSocket error: {e}")
    finally:
        manager.disconnect(session_id)
        # Update invitation status if not completed
        if invitation.status == "STARTED":
            invitation.status = "INTERRUPTED"
            await db.commit()