"""FastAPI router for AI Policy Assistant endpoints (/api/v1/ai/policy/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Dict, Any, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.policy_ai import (
    PolicyChatRequest,
    PolicyChatResponse,
    PolicyDocumentItem,
    PolicyDocumentsResponse,
    PolicyFeedbackRequest,
    PolicyFeedbackResponse,
    PolicyHistoryResponse,
    PolicySearchRequest,
    PolicySearchResponse,
    PolicySuggestionsResponse,
)
from app.services.policy_ai_service import PolicyAIService

router = APIRouter(prefix="/ai/policy", tags=["AI Policy Assistant"])


async def get_policy_ai_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PolicyAIService:
    return PolicyAIService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.post(
    "/chat",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyChatResponse],
    summary="Ask AI Policy Assistant Question (RAG)",
)
async def policy_chat(
    payload: PolicyChatRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicyChatResponse]:
    """Process user policy question via RAG vector embedding search and LLM completion with citations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.process_chat_query(request=payload, company_id=company_id)
    return APIResponse[PolicyChatResponse](
        success=True,
        message="Answer generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/search",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicySearchResponse],
    summary="Semantic HR Policy Search",
)
async def search_policies(
    payload: PolicySearchRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicySearchResponse]:
    """Execute vector cosine similarity search across company HR policy documents."""
    company_id = get_company_id_from_claims(claims)
    data = await service.search_policies(request=payload, company_id=company_id)
    return APIResponse[PolicySearchResponse](
        success=True,
        message="Policy search completed successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicySuggestionsResponse],
    summary="Get Suggested & Popular Policy Questions",
)
async def get_policy_suggestions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
    role: Optional[str] = Query(None),
) -> APIResponse[PolicySuggestionsResponse]:
    """Retrieve FAQ, popular, recently asked, and role-based policy question suggestions."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_suggestions(company_id=company_id, role=role)
    return APIResponse[PolicySuggestionsResponse](
        success=True,
        message="Policy suggestions fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyHistoryResponse],
    summary="Get Conversation History",
)
async def get_policy_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicyHistoryResponse]:
    """Retrieve overall policy chat history for current user/company."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history(company_id=company_id)
    return APIResponse[PolicyHistoryResponse](
        success=True,
        message="Policy chat history fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyHistoryResponse],
    summary="Get Conversation Details",
)
async def get_conversation_detail(
    conversation_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicyHistoryResponse]:
    """Retrieve chat logs for a specific conversation ID."""
    data = await service.get_history_detail(conversation_id=conversation_id)
    return APIResponse[PolicyHistoryResponse](
        success=True,
        message="Conversation history detail fetched successfully.",
        data=data,
        errors=None,
    )


@router.delete(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[Dict[str, Any]],
    summary="Delete Conversation History",
)
async def delete_conversation(
    conversation_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[Dict[str, Any]]:
    """Delete specific conversation history log."""
    data = await service.delete_history(conversation_id=conversation_id)
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Conversation deleted successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/documents",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyDocumentsResponse],
    summary="Get Available Policy Documents",
)
async def get_policy_documents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
    category: Optional[str] = Query(None),
) -> APIResponse[PolicyDocumentsResponse]:
    """Retrieve list of indexed company HR policy manuals."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_documents(company_id=company_id, category=category)
    return APIResponse[PolicyDocumentsResponse](
        success=True,
        message="Policy documents fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/document/{document_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyDocumentItem],
    summary="Get Specific Policy Document Detail",
)
async def get_policy_document_detail(
    document_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicyDocumentItem]:
    """Retrieve specific policy document details and chunk metadata."""
    data = await service.get_document_detail(document_id=document_id)
    return APIResponse[PolicyDocumentItem](
        success=True,
        message="Policy document detail fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyFeedbackResponse],
    summary="Submit AI Answer Feedback",
)
async def submit_policy_feedback(
    payload: PolicyFeedbackRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_policy_ai_service)],
) -> APIResponse[PolicyFeedbackResponse]:
    """Submit user rating feedback for an AI policy response."""
    data = await service.save_feedback(request=payload)
    return APIResponse[PolicyFeedbackResponse](
        success=True,
        message="Feedback submitted successfully.",
        data=data,
        errors=None,
    )
