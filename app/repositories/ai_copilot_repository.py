"""AI Hiring Copilot repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_copilot import (
    ResumeDocument,
    ResumeExtractedData,
    ResumeEmbedding,
    JobEmbedding,
    CandidateSimilarity,
    CandidateAiAnalysis,
    CandidateRanking,
    InterviewQuestion,
    AiLog,
)

logger = logging.getLogger(__name__)


class AiCopilotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Document CRUD
    # ------------------------------------------------------------------

    async def create_resume_document(self, **kwargs: Any) -> ResumeDocument:
        obj = ResumeDocument(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_resume_document_by_id(self, doc_uuid: uuid.UUID) -> ResumeDocument | None:
        result = await self.session.execute(
            select(ResumeDocument)
            .where(ResumeDocument.id == doc_uuid)
            .options(
                selectinload(ResumeDocument.extracted_data),
                selectinload(ResumeDocument.embeddings),
                selectinload(ResumeDocument.similarities),
                selectinload(ResumeDocument.ai_analyses),
                selectinload(ResumeDocument.rankings),
                selectinload(ResumeDocument.interview_questions),
            )
        )
        return result.scalar_one_or_none()

    async def get_resume_document_by_application_id(self, app_uuid: uuid.UUID) -> ResumeDocument | None:
        result = await self.session.execute(
            select(ResumeDocument)
            .where(ResumeDocument.application_id == app_uuid)
            .order_by(ResumeDocument.uploaded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Extraction CRUD
    # ------------------------------------------------------------------

    async def create_extracted_data(self, **kwargs: Any) -> ResumeExtractedData:
        obj = ResumeExtractedData(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_extracted_data(self, doc_uuid: uuid.UUID) -> ResumeExtractedData | None:
        result = await self.session.execute(
            select(ResumeExtractedData).where(ResumeExtractedData.resume_document_id == doc_uuid)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Embedding CRUD
    # ------------------------------------------------------------------

    async def create_resume_embedding(self, **kwargs: Any) -> ResumeEmbedding:
        obj = ResumeEmbedding(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_resume_embedding(self, doc_uuid: uuid.UUID) -> ResumeEmbedding | None:
        result = await self.session.execute(
            select(ResumeEmbedding).where(ResumeEmbedding.resume_document_id == doc_uuid)
        )
        return result.scalar_one_or_none()

    async def create_job_embedding(self, **kwargs: Any) -> JobEmbedding:
        obj = JobEmbedding(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_job_embedding(self, job_uuid: uuid.UUID) -> JobEmbedding | None:
        result = await self.session.execute(
            select(JobEmbedding).where(JobEmbedding.job_id == job_uuid)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Similarity matching CRUD
    # ------------------------------------------------------------------

    async def create_candidate_similarity(self, **kwargs: Any) -> CandidateSimilarity:
        obj = CandidateSimilarity(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_candidate_similarity(self, doc_uuid: uuid.UUID, job_uuid: uuid.UUID) -> CandidateSimilarity | None:
        result = await self.session.execute(
            select(CandidateSimilarity).where(
                and_(
                    CandidateSimilarity.resume_document_id == doc_uuid,
                    CandidateSimilarity.job_id == job_uuid,
                )
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # AI Qualitative Analyses CRUD
    # ------------------------------------------------------------------

    async def create_candidate_analysis(self, **kwargs: Any) -> CandidateAiAnalysis:
        obj = CandidateAiAnalysis(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_candidate_analysis(self, doc_uuid: uuid.UUID, job_uuid: uuid.UUID) -> CandidateAiAnalysis | None:
        result = await self.session.execute(
            select(CandidateAiAnalysis).where(
                and_(
                    CandidateAiAnalysis.resume_document_id == doc_uuid,
                    CandidateAiAnalysis.job_id == job_uuid,
                )
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Rankings CRUD
    # ------------------------------------------------------------------

    async def create_candidate_ranking(self, **kwargs: Any) -> CandidateRanking:
        obj = CandidateRanking(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_candidate_ranking(self, doc_uuid: uuid.UUID, job_uuid: uuid.UUID) -> CandidateRanking | None:
        result = await self.session.execute(
            select(CandidateRanking).where(
                and_(
                    CandidateRanking.resume_document_id == doc_uuid,
                    CandidateRanking.job_id == job_uuid,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_job_rankings(self, job_uuid: uuid.UUID) -> list[CandidateRanking]:
        result = await self.session.execute(
            select(CandidateRanking)
            .where(CandidateRanking.job_id == job_uuid)
            .order_by(CandidateRanking.overall_score.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Interview Questions CRUD
    # ------------------------------------------------------------------

    async def create_interview_questions(self, **kwargs: Any) -> InterviewQuestion:
        obj = InterviewQuestion(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_interview_questions(self, doc_uuid: uuid.UUID, job_uuid: uuid.UUID) -> InterviewQuestion | None:
        result = await self.session.execute(
            select(InterviewQuestion).where(
                and_(
                    InterviewQuestion.resume_document_id == doc_uuid,
                    InterviewQuestion.job_id == job_uuid,
                )
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # AI Process Auditing Logs
    # ------------------------------------------------------------------

    async def create_ai_log(self, **kwargs: Any) -> AiLog:
        obj = AiLog(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj
