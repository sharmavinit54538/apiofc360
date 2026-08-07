"""API v2 router for the AI Policy Explainer and RAG chatbot Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.policy_service import PolicyService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policies", tags=["AI Policy Explainer v2"])


# Requests
class UploadPolicyRequest(BaseModel):
    company_id: uuid.UUID
    title: str = Field(..., min_length=2)
    category: str = Field(..., description="LEAVE | TRAVEL | IT | SECURITY | PAYROLL | COMPLIANCE")
    raw_content: str = Field(..., min_length=10)

class ChatPolicyQuery(BaseModel):
    company_id: uuid.UUID
    query: str = Field(..., min_length=2)
    language: Optional[str] = "English"
    model: Optional[str] = None


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Upload policy manual and generate RAG vector chunk mappings",
)
async def upload_policy(
    body: UploadPolicyRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Saves policy text and calculates chunk embeddings using local nomic-embed-text."""
    service = PolicyService(db)
    doc = await service.upload_policy_document(
        company_id=body.company_id,
        title=body.title,
        category=body.category,
        raw_content=body.raw_content
    )
    return APIResponse[dict](
        success=True,
        message="Policy document uploaded and indexed successfully.",
        data={
            "document_id": str(doc.id),
            "title": doc.title,
            "category": doc.category,
        },
        errors=None
    )


@router.post(
    "/chat",
    response_model=APIResponse[dict],
    summary="Query company policies chatbot using vector search context",
)
async def query_chatbot(
    body: ChatPolicyQuery,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Searches vector chunks and runs local LLM to answer policy queries in any language."""
    service = PolicyService(db)
    result = await service.answer_policy_query(
        company_id=body.company_id,
        user_query=body.query,
        language=body.language,
        model=body.model
    )
    return APIResponse[dict](
        success=True,
        message="Policy query answered.",
        data=result,
        errors=None
    )
