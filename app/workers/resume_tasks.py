"""Background tasks for resume parsing and embedding generation.

These tasks run asynchronously via Celery when USE_CELERY=true.
When Celery is disabled, they fall back to synchronous execution.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE

    if CELERY_AVAILABLE and celery_app is not None:

        @celery_app.task(
            bind=True,
            name="app.workers.resume_tasks.parse_resume",
            max_retries=3,
            default_retry_delay=30,
        )
        def parse_resume_task(self, resume_document_id: str, file_path: str, model: str | None = None):
            """Async background task: parse a resume and store extracted data."""
            logger.info("parse_resume_task started | doc_id=%s", resume_document_id)
            try:
                result = _run_async(_parse_resume_async(resume_document_id, file_path, model))
                logger.info("parse_resume_task completed | doc_id=%s", resume_document_id)
                return result
            except Exception as exc:
                logger.error("parse_resume_task failed | doc_id=%s | %s", resume_document_id, exc)
                raise self.retry(exc=exc)

        @celery_app.task(
            bind=True,
            name="app.workers.resume_tasks.generate_embedding",
            max_retries=3,
            default_retry_delay=15,
        )
        def generate_embedding_task(
            self,
            candidate_id: str,
            resume_text: str,
            candidate_name: str,
            skills: list[str],
            job_id: str | None = None,
        ):
            """Async background task: generate and store resume embedding in vector store."""
            logger.info("generate_embedding_task started | candidate=%s", candidate_id)
            try:
                result = _run_async(
                    _generate_embedding_async(candidate_id, resume_text, candidate_name, skills, job_id)
                )
                return result
            except Exception as exc:
                logger.error("generate_embedding_task failed | candidate=%s | %s", candidate_id, exc)
                raise self.retry(exc=exc)

        @celery_app.task(
            bind=True,
            name="app.workers.resume_tasks.batch_screen_candidates",
            max_retries=2,
            default_retry_delay=60,
        )
        def batch_screen_candidates_task(self, job_id: str, candidate_ids: list[str], model: str | None = None):
            """Screen a batch of candidates for a job asynchronously."""
            logger.info("batch_screen started | job=%s | count=%d", job_id, len(candidate_ids))
            try:
                result = _run_async(_batch_screen_async(job_id, candidate_ids, model))
                return result
            except Exception as exc:
                logger.error("batch_screen_task failed | job=%s | %s", job_id, exc)
                raise self.retry(exc=exc)

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Async implementations (called by tasks OR directly in sync-fallback mode)
# ---------------------------------------------------------------------------

async def _parse_resume_async(
    resume_document_id: str,
    file_path: str,
    model: str | None = None,
) -> dict:
    """Core resume parsing logic (async)."""
    from app.agents.resume_parser import ResumeParserAgent
    from app.db.database import async_session_factory

    agent = ResumeParserAgent()
    parsed = await agent.parse_file(file_path, model=model)

    # Update DB record with parsed data
    async with async_session_factory() as db:
        from sqlalchemy import select, update
        from app.models.ai_recruitment import AIResumeDocument

        await db.execute(
            update(AIResumeDocument)
            .where(AIResumeDocument.id == uuid.UUID(resume_document_id))
            .values(
                parsed_data=parsed.to_dict(),
                raw_text=parsed.raw_text[:10000],
                parse_status="COMPLETED",
                ocr_engine_used=parsed.engine_used,
                candidate_name=parsed.name,
                candidate_email=parsed.email,
                years_experience=parsed.years_experience,
            )
        )
        await db.commit()

    logger.info("Resume %s parsed successfully (%d chars)", resume_document_id, len(parsed.raw_text))
    return {"status": "completed", "doc_id": resume_document_id}


async def _generate_embedding_async(
    candidate_id: str,
    resume_text: str,
    candidate_name: str,
    skills: list[str],
    job_id: str | None = None,
) -> dict:
    """Core embedding generation logic (async)."""
    from app.rag.hr_copilot_rag import HRCopilotRAG

    copilot = HRCopilotRAG()
    success = await copilot.index_candidate(
        candidate_id=candidate_id,
        candidate_name=candidate_name,
        resume_text=resume_text,
        skills=skills,
        job_id=job_id,
    )
    return {"status": "completed" if success else "failed", "candidate_id": candidate_id}


async def _batch_screen_async(
    job_id: str,
    candidate_ids: list[str],
    model: str | None = None,
) -> dict:
    """Batch screening implementation loading actual candidate data from DB and running screening engine."""
    logger.info("Starting batch screening for job %s with %d candidates", job_id, len(candidate_ids))
    success_count = 0
    from app.db.database import AsyncSessionLocal
    from app.models.recruitment import CandidateApplication
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        stmt = select(CandidateApplication).where(CandidateApplication.job_id == job_id)
        if candidate_ids:
            stmt = stmt.where(CandidateApplication.id.in_(candidate_ids))
        res = await session.execute(stmt)
        candidates = res.scalars().all()

        for cand in candidates:
            try:
                ok = await _screen_candidate_async(
                    candidate_id=str(cand.id),
                    candidate_name=f"{cand.first_name} {cand.last_name}",
                    resume_text=cand.resume_text or "",
                    skills=cand.skills or [],
                    job_id=str(cand.job_id),
                )
                if ok:
                    success_count += 1
            except Exception as exc:
                logger.error("Error screening candidate %s: %s", cand.id, exc)

    return {
        "status": "completed",
        "job_id": job_id,
        "total_requested": len(candidate_ids),
        "screened": success_count,
    }


# ---------------------------------------------------------------------------
# Sync fallback dispatcher (used when USE_CELERY=false)
# ---------------------------------------------------------------------------

async def dispatch_parse_resume(
    resume_document_id: str,
    file_path: str,
    model: str | None = None,
) -> dict:
    """Dispatch resume parsing — uses Celery if available, sync otherwise."""
    from app.core.config import settings

    if settings.USE_CELERY:
        try:
            from app.workers.resume_tasks import parse_resume_task
            parse_resume_task.delay(resume_document_id, file_path, model)
            return {"status": "queued", "doc_id": resume_document_id}
        except Exception as exc:
            logger.warning("Celery dispatch failed, running synchronously: %s", exc)

    return await _parse_resume_async(resume_document_id, file_path, model)


async def dispatch_generate_embedding(
    candidate_id: str,
    resume_text: str,
    candidate_name: str,
    skills: list[str],
    job_id: str | None = None,
) -> dict:
    """Dispatch embedding generation — Celery or sync."""
    from app.core.config import settings

    if settings.USE_CELERY:
        try:
            from app.workers.resume_tasks import generate_embedding_task
            generate_embedding_task.delay(candidate_id, resume_text, candidate_name, skills, job_id)
            return {"status": "queued", "candidate_id": candidate_id}
        except Exception as exc:
            logger.warning("Celery dispatch failed, running synchronously: %s", exc)

    return await _generate_embedding_async(candidate_id, resume_text, candidate_name, skills, job_id)
