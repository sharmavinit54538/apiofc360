"""WebSocket endpoints for real-time AI Video Interview with Audio Pipeline."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from enum import Enum

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status, WebSocketException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims_optional
from app.repositories.recruitment_repository import RecruitmentRepository
from app.services.ai_interview_service import AIInterviewService
from app.services.stt.service import STTInterviewService
from app.services.tts.service import TTSInterviewService
from app.models.ai_interview import AIInterviewSession
from app.models.recruitment import InterviewInvitation
from app.models.interview_recording import InterviewRecording, MediaType, RecordingStatus

router = APIRouter(prefix="/interview-ws", tags=["AI Interview WebSocket"])


class MessageType(str, Enum):
    """WebSocket message types."""
    # Client -> Server
    AUDIO_CHUNK = "audio_chunk"
    ANSWER_TEXT = "answer_text"
    DEVICE_CHECK = "device_check"
    CONSENT = "consent"
    PROCTOR_ALERT = "proctor_alert"
    PING = "ping"
    RECONNECT = "reconnect"
    
    # Server -> Client
    SESSION_STARTED = "session_started"
    QUESTION_AUDIO = "question_audio"
    QUESTION_TEXT = "question_text"
    ANSWER_EVALUATED = "answer_evaluated"
    TRANSCRIPTION_PARTIAL = "transcription_partial"
    TRANSCRIPTION_FINAL = "transcription_final"
    TTS_AUDIO = "tts_audio"
    TTS_COMPLETE = "tts_complete"
    SESSION_COMPLETED = "session_completed"
    PROCTOR_ACK = "proctor_ack"
    PONG = "pong"
    RECONNECTED = "reconnected"
    ERROR = "error"
    DEVICE_CHECK_RESULT = "device_check_result"
    CONSENT_RESULT = "consent_result"


class ConnectionManager:
    """Manage active WebSocket connections for interview sessions."""

    def __init__(self):
        self.active_connections: dict[uuid.UUID, WebSocket] = {}
        self.connection_metadata: dict[uuid.UUID, dict] = {}

    async def connect(self, session_id: uuid.UUID, websocket: WebSocket, metadata: dict = None):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.connection_metadata[session_id] = metadata or {}

    def disconnect(self, session_id: uuid.UUID):
        self.active_connections.pop(session_id, None)
        self.connection_metadata.pop(session_id, None)

    async def send_json(self, session_id: uuid.UUID, data: dict):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(data)

    async def send_bytes(self, session_id: uuid.UUID, data: bytes):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_bytes(data)

    def is_connected(self, session_id: uuid.UUID) -> bool:
        return session_id in self.active_connections


manager = ConnectionManager()


async def get_interview_session_ws(
    token: str = Query(..., description="Interview invitation token"),
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> AIInterviewSession:
    """Validate interview invitation token and return session."""
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
    """WebSocket endpoint for real-time AI video interview with audio pipeline.
    
    Client flow:
    1. Connect with invitation token
    2. Send device_check message with camera/mic permissions
    3. Send consent message
    4. Receive session_started with first question (text + TTS audio)
    5. Send audio_chunk messages for candidate's spoken answer
    6. Receive transcription_partial/final and TTS audio for AI response
    7. Continue until session_completed
    8. Handle reconnection within grace period
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
        ai_service = AIInterviewService(db)
        ai_session = await ai_service.initialize_session(
            candidate_id=invitation.candidate_id,
            job_id=invitation.interview.job_id if invitation.interview else None,
            interview_type="VIDEO",
            company_id=invitation.company_id,
            round_id=invitation.round_id,
        )
    
    session_id = ai_session.id
    
    # Initialize services
    stt_service = STTInterviewService(db)
    tts_service = TTSInterviewService(db)
    ai_service = AIInterviewService(db)
    
    # Handle reconnection
    if invitation.status == "STARTED" and session_id in manager.active_connections:
        old_ws = manager.active_connections[session_id]
        try:
            await old_ws.close(code=status.WS_1000_NORMAL_CLOSURE, reason="Reconnected")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to close old WebSocket connection: %s", exc)
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
    
    # Initialize recording if consent given
    recording = None
    
    # Connect
    metadata = {
        "invitation_id": str(invitation.id),
        "session_id": str(session_id),
        "candidate_id": str(invitation.candidate_id),
    }
    await manager.connect(session_id, websocket, metadata)
    
    # Audio buffering for streaming STT
    audio_buffer = bytearray()
    audio_buffer_lock = asyncio.Lock()
    is_processing_audio = False
    
    try:
        # Send initial session info
        question = None
        if ai_session.current_question_index < len(ai_session.questions):
            question = ai_session.questions[ai_session.current_question_index]
        
        await websocket.send_json({
            "type": MessageType.SESSION_STARTED.value,
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
        await ai_service.start_session(session_id)
        
        # Send first question as TTS audio
        if question:
            try:
                audio_data = await tts_service.synthesize_question(
                    session_id=session_id,
                    question_id=question.id,
                )
                # Send as base64 encoded audio
                audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                await websocket.send_json({
                    "type": MessageType.QUESTION_AUDIO.value,
                    "question_id": str(question.id),
                    "audio_data": audio_b64,
                    "format": "mp3",
                    "sample_rate": 22050,
                })
            except Exception as e:
                logger.warning(f"TTS synthesis failed for first question: {e}")
        
        # Also send question text
        if question:
            await websocket.send_json({
                "type": MessageType.QUESTION_TEXT.value,
                "question_id": str(question.id),
                "text": question.question_text,
                "type": question.question_type,
                "difficulty": question.difficulty,
            })
        
        # Audio processing state
        current_question_id = question.id if question else None
        current_audio_buffer = bytearray()
        last_transcription_time = datetime.now(timezone.utc)
        transcription_interval = 2.0  # seconds between interim transcriptions
        
        async def process_audio_buffer():
            """Process accumulated audio buffer through STT."""
            nonlocal current_audio_buffer, last_transcription_time, current_question_id
            
            if not current_audio_buffer or not current_question_id:
                return
            
            async with audio_buffer_lock:
                if len(current_audio_buffer) < 1600:  # Less than 100ms at 16kHz 16-bit
                    return
                
                audio_data = bytes(current_audio_buffer)
                current_audio_buffer.clear()
            
            try:
                # Transcribe audio
                text = await stt_service.transcribe_answer(
                    session_id=session_id,
                    question_id=current_question_id,
                    audio_data=audio_data,
                    language="en",
                    sample_rate=16000,
                )
                
                # Send final transcription
                await websocket.send_json({
                    "type": MessageType.TRANSCRIPTION_FINAL.value,
                    "question_id": str(current_question_id),
                    "text": text,
                    "confidence": 0.9,
                    "language": "en",
                })
                
                # Evaluate answer
                result = await ai_service.submit_answer(
                    session_id=session_id,
                    question_id=current_question_id,
                    candidate_response=text,
                    duration_seconds=0,  # Will be calculated from audio
                )
                
                # Send evaluation
                await websocket.send_json({
                    "type": MessageType.ANSWER_EVALUATED.value,
                    "question_id": str(current_question_id),
                    "score_logged": result.get("score_logged"),
                    "evaluation_status": result.get("evaluation_status"),
                    "evaluation": result.get("evaluation"),
                    "next_question": result.get("next_question"),
                    "session_status": result.get("session_status"),
                })
                
                # Generate TTS for evaluation feedback
                if result.get("evaluation"):
                    try:
                        tts_audio = await tts_service.provider.synthesize(
                            result["evaluation"],
                            voice=None,
                            language="en",
                            speed=1.0,
                        )
                        audio_b64 = base64.b64encode(tts_audio.audio_data).decode('utf-8')
                        await websocket.send_json({
                            "type": MessageType.TTS_AUDIO.value,
                            "audio_data": audio_b64,
                            "format": tts_audio.format,
                            "sample_rate": tts_audio.sample_rate,
                        })
                    except Exception as e:
                        logger.warning(f"TTS for evaluation failed: {e}")
                
                # Handle next question
                next_q = result.get("next_question")
                if next_q:
                    current_question_id = uuid.UUID(next_q["id"])
                    
                    # Send next question text
                    await websocket.send_json({
                        "type": MessageType.QUESTION_TEXT.value,
                        "question_id": next_q["id"],
                        "text": next_q["text"],
                        "type": next_q["type"],
                        "difficulty": next_q["difficulty"],
                    })
                    
                    # Send next question TTS audio
                    try:
                        audio_data = await tts_service.synthesize_question(
                            session_id=session_id,
                            question_id=current_question_id,
                        )
                        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                        await websocket.send_json({
                            "type": MessageType.QUESTION_AUDIO.value,
                            "question_id": str(current_question_id),
                            "audio_data": audio_b64,
                            "format": "mp3",
                            "sample_rate": 22050,
                        })
                    except Exception as e:
                        logger.warning(f"TTS synthesis failed for next question: {e}")
                else:
                    # Session completed
                    await websocket.send_json({
                        "type": MessageType.SESSION_COMPLETED.value,
                        "session_id": str(session_id),
                    })
                    
            except Exception as e:
                logger.error(f"Audio processing failed: {e}")
                await websocket.send_json({
                    "type": MessageType.ERROR.value,
                    "message": "Failed to process audio. Please try again.",
                })
        
        # Message loop
        while True:
            try:
                message = await websocket.receive()
                
                if "bytes" in message:
                    # Binary audio chunk
                    audio_data = message["bytes"]
                    
                    async with audio_buffer_lock:
                        current_audio_buffer.extend(audio_data)
                    
                    # Check if enough time passed for interim transcription
                    now = datetime.now(timezone.utc)
                    if (now - last_transcription_time).total_seconds() >= transcription_interval:
                        last_transcription_time = now
                        asyncio.create_task(process_audio_buffer())
                        
                elif "text" in message:
                    # Text message
                    try:
                        msg = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue
                    
                    msg_type = msg.get("type")
                    
                    if msg_type == MessageType.DEVICE_CHECK.value:
                        # Handle device check
                        has_camera = msg.get("has_camera", False)
                        has_microphone = msg.get("has_microphone", False)
                        camera_test = msg.get("camera_test_passed", False)
                        mic_test = msg.get("microphone_test_passed", False)
                        browser_info = msg.get("browser_info", "")
                        
                        if not has_camera or not has_microphone or not camera_test or not mic_test:
                            await websocket.send_json({
                                "type": MessageType.DEVICE_CHECK_RESULT.value,
                                "success": False,
                                "message": "Camera and microphone are required for the interview.",
                            })
                        else:
                            # Update invitation
                            invitation.device_check_completed = True
                            await db.commit()
                            
                            await websocket.send_json({
                                "type": MessageType.DEVICE_CHECK_RESULT.value,
                                "success": True,
                                "message": "Device check passed. You may proceed.",
                            })
                            
                    elif msg_type == MessageType.CONSENT.value:
                        # Handle consent
                        consent_given = msg.get("consent_given", False)
                        
                        if not consent_given:
                            await websocket.send_json({
                                "type": MessageType.CONSENT_RESULT.value,
                                "success": False,
                                "message": "Consent is required to proceed with the interview.",
                            })
                        else:
                            invitation.consent_given = True
                            invitation.consent_at = datetime.now(timezone.utc)
                            await db.commit()
                            
                            # Start recording
                            try:
                                from app.services.recording_service import RecordingService
                                recording_service = RecordingService(db)
                                recording = await recording_service.start_recording(
                                    session_id=session_id,
                                    candidate_id=invitation.candidate_id,
                                    job_id=ai_session.job_id,
                                    round_id=invitation.round_id,
                                    media_type=MediaType.AUDIO,
                                    format="webm",
                                    consent_given=True,
                                    consent_version="1.0",
                                    company_id=invitation.company_id,
                                )
                                recording = recording
                            except Exception as e:
                                logger.warning(f"Recording start failed: {e}")
                            
                            await websocket.send_json({
                                "type": MessageType.CONSENT_RESULT.value,
                                "success": True,
                                "message": "Consent recorded. You may now start the interview.",
                            })
                            
                    elif msg_type == MessageType.ANSWER_TEXT.value:
                        # Handle text-based answer (fallback)
                        question_id = uuid.UUID(msg.get("question_id"))
                        candidate_response = msg.get("candidate_response", "")
                        duration_seconds = msg.get("duration_seconds", 0)
                        
                        result = await ai_service.submit_answer(
                            session_id=session_id,
                            question_id=question_id,
                            candidate_response=candidate_response,
                            duration_seconds=duration_seconds,
                        )
                        
                        await websocket.send_json({
                            "type": MessageType.ANSWER_EVALUATED.value,
                            "question_id": str(question_id),
                            "score_logged": result.get("score_logged"),
                            "evaluation_status": result.get("evaluation_status"),
                            "evaluation": result.get("evaluation"),
                            "next_question": result.get("next_question"),
                            "session_status": result.get("session_status"),
                        })
                        
                        # Handle next question...
                        next_q = result.get("next_question")
                        if next_q:
                            await websocket.send_json({
                                "type": MessageType.QUESTION_TEXT.value,
                                "question_id": next_q["id"],
                                "text": next_q["text"],
                                "type": next_q["type"],
                                "difficulty": next_q["difficulty"],
                            })
                        else:
                            await websocket.send_json({
                                "type": MessageType.SESSION_COMPLETED.value,
                                "session_id": str(session_id),
                            })
                            
                    elif msg_type == MessageType.PROCTOR_ALERT.value:
                        alert_type = msg.get("alert_type")
                        details = msg.get("details", "")
                        await ai_service.log_proctoring_alert(session_id, alert_type, details)
                        await websocket.send_json({"type": MessageType.PROCTOR_ACK.value, "alert_type": alert_type})
                        
                    elif msg_type == MessageType.PING.value:
                        await websocket.send_json({"type": MessageType.PONG.value})
                        
                    elif msg_type == MessageType.RECONNECT.value:
                        invitation.reconnect_count += 1
                        invitation.grace_period_ends_at = datetime.now(timezone.utc) + timedelta(minutes=30)
                        await db.commit()
                        await websocket.send_json({"type": MessageType.RECONNECTED.value, "grace_period_ends_at": invitation.grace_period_ends_at.isoformat()})
                        
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                continue
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception(f"Interview WebSocket error: {e}")
    finally:
        manager.disconnect(session_id)
        if invitation.status == "STARTED":
            invitation.status = "INTERRUPTED"
            await db.commit()
        
        # Update recording status if exists
        if recording:
            try:
                from app.services.recording_service import RecordingService
                recording_service = RecordingService(db)
                await recording_service.finalize_recording(
                    recording_id=recording.id,
                    total_duration_seconds=0,  # Will be calculated from chunks
                )
            except Exception as e:
                logger.error(f"Recording finalization failed: {e}")

from datetime import datetime, timedelta, timezone
import asyncio
import base64