"""STT Service for AI Interview integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_interview import AIInterviewSession, AIInterviewQuestionInstance, AIInterviewResponse
from app.services.stt.providers import get_stt_provider, get_stt_router

logger = logging.getLogger(__name__)


class STTInterviewService:
    """STT service for AI interview voice transcription."""

    def __init__(self, db: AsyncSession, provider_name: str = "deepgram") -> None:
        self.db = db
        self.provider = get_stt_provider(provider_name)

    async def health_check(self) -> bool:
        return await self.provider.health_check()

    async def transcribe_answer(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        audio_data: bytes,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> str:
        """Transcribe candidate's audio answer to text."""
        from app.services.stt.providers import TranscriptionResult
        
        result: TranscriptionResult = await self.provider.transcribe(
            audio_data,
            language=language,
            sample_rate=sample_rate,
        )
        
        # Store transcription in the response record
        from app.models.ai_interview import AIInterviewResponse
        from sqlalchemy import select
        
        stmt = select(AIInterviewResponse).where(
            AIInterviewResponse.question_id == question_id,
            AIInterviewResponse.interview_session_id == session_id,
        )
        res = await self.db.execute(stmt)
        response = res.scalar_one_or_none()
        
        if response:
            response.candidate_response = result.text
            response.transcription_confidence = result.confidence
            response.transcription_language = result.language
            response.transcription_duration = result.duration_seconds
            await self.db.commit()
        
        return result.text

    async def transcribe_stream(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        audio_stream,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        interim_results: bool = True,
    ):
        """Transcribe streaming audio and yield interim results."""
        from app.services.stt.providers import StreamingTranscriptionResult
        
        async for chunk_result in self.provider.transcribe_stream(
            audio_stream,
            language=language,
            sample_rate=sample_rate,
            interim_results=True,
        ):
            # Store interim results if needed
            if chunk_result.is_final:
                # Update the response with final transcription
                from app.models.ai_interview import AIInterviewResponse
                from sqlalchemy import select
                
                stmt = select(AIInterviewResponse).where(
                    AIInterviewResponse.question_id == question_id,
                    AIInterviewResponse.interview_session_id == session_id,
                )
                res = await self.db.execute(stmt)
                response = res.scalar_one_or_none()
                
                if response:
                    response.candidate_response = chunk_result.text
                    response.transcription_confidence = chunk_result.confidence
                    response.transcription_language = chunk_result.language
                    await self.db.commit()
            
            yield chunk_result

    async def transcribe_batch(
        self,
        audio_files: list[bytes],
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> list[str]:
        """Transcribe multiple audio files in batch."""
        texts = []
        for audio_data in audio_files:
            text = await self.transcribe_answer(
                session_id=uuid.uuid4(),  # dummy session for batch
                question_id=uuid.uuid4(),  # dummy question for batch
                audio_data=audio_data,
                language=language,
                sample_rate=sample_rate,
            )
            texts.append(text)
        return texts


class STTServiceFactory:
    """Factory for creating STT services with appropriate providers."""

    @staticmethod
    def create_service(
        db: AsyncSession,
        provider_name: Optional[str] = None,
    ):
        if provider_name is None:
            provider_name = "deepgram"
        return STTInterviewService(db, provider_name)

    @staticmethod
    async def get_best_provider() -> str:
        """Get the best available STT provider."""
        from app.services.stt.providers import get_available_stt_providers
        
        for name in ["deepgram", "whisper", "google_cloud"]:
            if name in get_available_stt_providers():
                return name
        return "mock"