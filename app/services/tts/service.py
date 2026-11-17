"""TTS Service for AI Interview integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_interview import AIInterviewSession, AIInterviewQuestionInstance, AIInterviewResponse
from app.services.tts.providers import get_tts_provider, get_tts_router

logger = logging.getLogger(__name__)


class TTSInterviewService:
    """TTS service for AI interview voice responses."""

    def __init__(self, db: AsyncSession, provider_name: str = "elevenlabs") -> None:
        self.db = db
        self.provider = get_tts_provider(provider_name)
        self._streaming_sessions: dict[uuid.UUID, asyncio.Queue] = {}

    async def health_check(self) -> bool:
        return await self.provider.health_check()

    async def synthesize_question(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize a question text to audio for the candidate."""
        # Get the question text
        stmt = select(AIInterviewQuestionInstance).where(
            AIInterviewQuestionInstance.id == question_id,
            AIInterviewQuestionInstance.interview_session_id == session_id,
        )
        res = await self.db.execute(stmt)
        question = res.scalar_one_or_none()
        
        if not question:
            raise ValueError("Question not found")

        result = await self.provider.synthesize(
            question.question_text,
            voice=voice,
            language=language,
            speed=1.0,
        )
        
        # Store the audio reference in the question if needed
        question.tts_audio_generated = True
        question.tts_voice = voice
        question.tts_language = language
        await self.db.commit()
        
        return result.audio_data

    async def synthesize_question_stream(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized question audio."""
        stmt = select(AIInterviewQuestionInstance).where(
            AIInterviewQuestionInstance.id == question_id,
            AIInterviewQuestionInstance.interview_session_id == session_id,
        )
        res = await self.db.execute(stmt)
        question = res.scalar_one_or_none()
        
        if not question:
            raise ValueError("Question not found")

        async for chunk in self.provider.synthesize_stream(
            question.question_text,
            voice=voice,
            language=language,
            speed=1.0,
        ):
            yield chunk.audio_chunk

    async def synthesize_response_feedback(
        self,
        session_id: uuid.UUID,
        response_id: uuid.UUID,
        feedback_text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> bytes:
        """Synthesize feedback text for a candidate response."""
        result = await self.provider.synthesize(
            feedback_text,
            voice=voice,
            language=language,
            speed=0.9,  # Slightly slower for feedback
        )
        return result.audio_data

    async def synthesize_welcome_message(
        self,
        session_id: uuid.UUID,
        candidate_name: str,
        job_title: str,
        company_name: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> bytes:
        """Synthesize a welcome message for the interview start."""
        welcome_text = (
            f"Hello {candidate_name}. Welcome to your interview for the {job_title} "
            f"position at {company_name}. I'm your AI interviewer. "
            f"Let's begin with the first question."
        )
        
        result = await self.provider.synthesize(
            welcome_text,
            voice=voice,
            language=language,
            speed=1.0,
        )
        return result.audio_data

    async def synthesize_closing_message(
        self,
        session_id: uuid.UUID,
        candidate_name: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> bytes:
        """Synthesize a closing message for interview completion."""
        closing_text = (
            f"Thank you {candidate_name} for completing the interview. "
            f"Your responses have been recorded and will be reviewed by our hiring team. "
            f"You'll hear back from us soon. Have a great day!"
        )
        
        result = await self.provider.synthesize(
            closing_text,
            voice=voice,
            language=language,
            speed=1.0,
        )
        return result.audio_data

    async def stream_welcome_message(
        self,
        session_id: uuid.UUID,
        candidate_name: str,
        job_title: str,
        company_name: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream welcome message audio."""
        welcome_text = (
            f"Hello {candidate_name}. Welcome to your interview for the {job_title} "
            f"position at {company_name}. I'm your AI interviewer. "
            f"Let's begin with the first question."
        )
        
        async for chunk in self.provider.synthesize_stream(
            welcome_text,
            voice=voice,
            language=language,
            speed=1.0,
        ):
            yield chunk.audio_chunk

    async def stream_closing_message(
        self,
        session_id: uuid.UUID,
        candidate_name: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream closing message audio."""
        closing_text = (
            f"Thank you {candidate_name} for completing the interview. "
            f"Your responses have been recorded and will be reviewed by our hiring team. "
            f"You'll hear back from us soon. Have a great day!"
        )
        
        async for chunk in self.provider.synthesize_stream(
            closing_text,
            voice=voice,
            language=language,
            speed=1.0,
        ):
            yield chunk.audio_chunk


class TTSServiceFactory:
    """Factory for creating TTS services with appropriate providers."""

    @staticmethod
    def create_service(
        db: AsyncSession,
        provider_name: Optional[str] = None,
    ) -> TTSInterviewService:
        if provider_name is None:
            provider_name = "elevenlabs"
        return TTSInterviewService(db, provider_name)

    @staticmethod
    async def get_best_provider() -> str:
        """Get the best available TTS provider."""
        from app.services.tts.providers import get_available_tts_providers
        
        for name in ["elevenlabs", "openai", "google_cloud", "azure", "coqui"]:
            if name in get_available_tts_providers():
                return name
        return "mock"