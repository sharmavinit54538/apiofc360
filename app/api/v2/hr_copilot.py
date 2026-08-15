"""HR Copilot API v2 — Natural language Q&A over candidate database."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.rag.hr_copilot_rag import HRCopilotRAG, get_hr_copilot
from app.rag.retriever import get_retriever
from app.schemas.auth import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/hr-copilot",
    tags=["HR Copilot RAG v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class CopilotQueryRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=500, description="Natural language HR query")
    top_k: int = Field(10, ge=1, le=50, description="Number of candidate profiles to retrieve")
    job_id: str | None = Field(None, description="Optional job ID to scope results")
    model: str | None = None


class IndexCandidateRequest(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    resume_text: str = Field(..., min_length=50)
    skills: list[str] = Field(default_factory=list, max_length=100)
    job_id: str | None = None


class IndexJobRequest(BaseModel):
    job_id: uuid.UUID
    job_title: str
    jd_text: str = Field(..., min_length=50)
    department: str


@router.post(
    "/query",
    response_model=APIResponse[dict],
    summary="Ask the HR Copilot a natural language question",
)
async def query_hr_copilot(
    body: CopilotQueryRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Ask the AI-powered HR Copilot a natural language question."""
    copilot = get_hr_copilot()

    response = await copilot.query(
        question=body.question,
        top_k=body.top_k,
        job_id=body.job_id,
        model=body.model,
    )

    # Log query to DB for analytics
    from app.models.ai_recruitment import HRCopilotQuery
    query_log = HRCopilotQuery(
        user_id=uuid.UUID(claims["sub"]) if claims and "sub" in claims else uuid.uuid4(),
        company_id=uuid.UUID(claims.get("company_id", str(uuid.uuid4()))) if claims else None,
        question=body.question,
        answer=response.answer,
        intent=response.intent,
        retrieved_count=response.retrieved_count,
        confidence=response.confidence,
        model_used=body.model,
    )
    db.add(query_log)
    await db.commit()

    return APIResponse[dict](
        success=True,
        message="HR Copilot response generated.",
        data=response.to_dict(),
        errors=None,
    )


@router.post(
    "/index/candidate",
    response_model=APIResponse[dict],
    summary="Index a candidate in the vector store",
)
async def index_candidate(
    body: IndexCandidateRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
) -> APIResponse[dict]:
    """Embed and index a candidate's resume for semantic search."""
    copilot = get_hr_copilot()
    success = await copilot.index_candidate(
        candidate_id=str(body.candidate_id),
        candidate_name=body.candidate_name,
        resume_text=body.resume_text,
        skills=body.skills,
        job_id=body.job_id,
    )

    return APIResponse[dict](
        success=success,
        message="Candidate indexed successfully." if success else "Indexing failed.",
        data={"candidate_id": str(body.candidate_id), "indexed": success},
        errors=None if success else {"detail": "Embedding or vector store error"},
    )


@router.post(
    "/index/job",
    response_model=APIResponse[dict],
    summary="Index a job description in the vector store",
)
async def index_job(
    body: IndexJobRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
) -> APIResponse[dict]:
    """Embed and index a job description for semantic search."""
    copilot = get_hr_copilot()
    success = await copilot.index_job(
        job_id=str(body.job_id),
        job_title=body.job_title,
        jd_text=body.jd_text,
        department=body.department,
    )

    return APIResponse[dict](
        success=success,
        message="Job indexed successfully." if success else "Indexing failed.",
        data={"job_id": str(body.job_id), "indexed": success},
        errors=None if success else {"detail": "Embedding or vector store error"},
    )


@router.get(
    "/vector-store/status",
    response_model=APIResponse[dict],
    summary="Get vector store statistics",
)
async def get_vector_store_status(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
) -> APIResponse[dict]:
    """Return the current state of the vector store."""
    from app.core.config import settings
    retriever = get_retriever()
    count = retriever.count_indexed()

    return APIResponse[dict](
        success=True,
        message="Vector store status retrieved.",
        data={
            "backend": settings.VECTOR_STORE_TYPE,
            "total_indexed_documents": count,
            "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
            "embedding_dim": settings.VECTOR_EMBEDDING_DIM,
        },
        errors=None,
    )


@router.delete(
    "/index/candidate/{candidate_id}",
    response_model=APIResponse[dict],
    summary="Remove a candidate from the vector index",
)
async def remove_candidate_from_index(
    candidate_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
) -> APIResponse[dict]:
    """Remove a candidate's embedding from the vector store."""
    retriever = get_retriever()
    deleted = retriever.remove_document(str(candidate_id))

    return APIResponse[dict](
        success=deleted,
        message="Candidate removed from index." if deleted else "Candidate not found in index.",
        data={"candidate_id": str(candidate_id), "deleted": deleted},
        errors=None,
    )
