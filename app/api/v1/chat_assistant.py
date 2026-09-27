"""FastAPI router for AI Chat Assistant (Aurix AI Copilot) endpoints (/api/v1/ai/chat/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.chat_assistant import (
    AnalyticsQueryPayload,
    ChatAssistantRequest,
    ChatAssistantResponse,
    ChatFeedbackRequest,
    ChatHistoryResponse,
    ChatSuggestionsResponse,
    CreateConversationRequest,
    RecommendationsPayload,
    ReportGeneratePayload,
)
from app.services.chat_assistant_service import ChatAssistantService

router = APIRouter(prefix="/ai/chat", tags=["AI Chat Assistant"])


async def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatAssistantService:
    return ChatAssistantService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    """Extract and validate company_id from JWT claims enforcing tenant isolation."""
    if not isinstance(claims, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication claims.",
        )
    raw = claims.get("company_id")
    if not raw:
        if claims.get("role") in {"super_admin", "SUPER_ADMIN"} or claims.get("is_super_admin"):
            return None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not associated with a company (missing company_id in token).",
        )
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid company_id in authentication token.",
        )


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Process Natural Language AI Chat Query",
)
@router.post(
    "/",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Process Natural Language AI Chat Query (Slash)",
    include_in_schema=False,
)
@router.post(
    "/message",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Send Message to AI Assistant (Alias)",
)
@router.post(
    "/query",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Process Natural Language Chat Query (Alias)",
)
async def chat_with_assistant(
    request: ChatAssistantRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Process enterprise HRMS natural language user queries with RAG knowledge search, SQL analytics, markdown answers, citations, charts, tables, and follow-up prompts."""
    company_id = get_company_id_from_claims(claims)
    data = await service.process_chat(request=request, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="AI chat response generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Create New Chat Conversation",
)
async def create_chat_conversation(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
    payload: Optional[CreateConversationRequest] = Body(None),
) -> APIResponse[ChatAssistantResponse]:
    """Start a new chat conversation with an optional initial prompt or title."""
    company_id = get_company_id_from_claims(claims)
    user_id = claims.get("sub")
    conv_id = str(uuid.uuid4())

    init_msg = None
    if payload:
        init_msg = (payload.initial_message or payload.message or payload.query or payload.content or "").strip()

    if init_msg:
        req = ChatAssistantRequest(
            query=init_msg,
            message=init_msg,
            content=init_msg,
            conversation_id=conv_id,
            department_id=payload.department_id if payload else None,
        )
        data = await service.process_chat(request=req, company_id=company_id)
        if payload and payload.title:
            session = service.memory.get(conv_id)
            if session:
                session.metadata["title"] = payload.title
    else:
        title = payload.title if (payload and payload.title) else "New Conversation"
        session = service.memory.get_or_create(
            session_id=conv_id,
            user_id=str(user_id) if user_id else None,
            system_prompt="You are Aurix AI Copilot, an enterprise HRMS & Workforce Intelligence AI assistant.",
        )
        if company_id:
            session.metadata["company_id"] = str(company_id)
        session.metadata["title"] = title

        greeting = (
            f"Hello! I am Aurix AI Copilot, your enterprise HRMS assistant for {title}. "
            "How can I assist you with workforce analytics, policies, or HR operations today?"
        )
        session.add_message("assistant", greeting)

        data = ChatAssistantResponse(
            answer=greeting,
            confidence=1.0,
            sources=[],
            charts=[],
            tables=[],
            followUpQuestions=[
                "Show current workforce overview",
                "What are the open positions?",
                "Show recent hiring activity",
            ],
            follow_up_questions=[
                "Show current workforce overview",
                "What are the open positions?",
                "Show recent hiring activity",
            ],
            conversationId=conv_id,
            conversation_id=conv_id,
        )

    return APIResponse[ChatAssistantResponse](
        success=True,
        message="Conversation created successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/report",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Generate HR Report via AI Copilot",
)
async def generate_hr_report(
    payload: ReportGeneratePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Generate specialized export-ready HR reports (Attendance, Payroll, Leave, Performance, Recruitment, Compliance)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_hr_report(payload=payload, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="HR report generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Run Workforce Analytics Query",
)
async def run_workforce_analytics(
    payload: AnalyticsQueryPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Analyze headcount, attrition, hiring, productivity, utilization, and overtime metrics."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_analytics(payload=payload, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="Workforce analytics query completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/recommendations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Generate AI Copilot Recommendations",
)
async def generate_ai_recommendations(
    payload: RecommendationsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Generate promotion, retention, hiring, training, and cost optimization recommendations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_recommendations(payload=payload, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="AI recommendations generated successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatHistoryResponse],
    summary="Get Chat Conversation History",
)
@router.get(
    "/conversations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatHistoryResponse],
    summary="List Chat Conversations (Alias)",
)
async def get_chat_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatHistoryResponse]:
    """Retrieve list of user's past chat conversations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history(company_id=company_id)
    return APIResponse[ChatHistoryResponse](
        success=True,
        message="Chat history fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Get Specific Chat Conversation Detail",
)
@router.get(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Get Specific Chat Conversation Detail (Alias)",
)
async def get_chat_history_detail(
    conversation_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Retrieve details and messages of a single chat conversation."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history_detail(conversation_id=conversation_id, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="Conversation detail fetched successfully.",
        data=data,
        errors=None,
    )


@router.delete(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Delete Chat Conversation",
)
@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Delete Chat Conversation (Alias)",
)
async def delete_chat_history(
    conversation_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[dict]:
    """Delete a chat conversation history record."""
    company_id = get_company_id_from_claims(claims)
    data = await service.delete_history(conversation_id=conversation_id, company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="Conversation deleted successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatSuggestionsResponse],
    summary="Get Suggested Copilot Prompts",
)
async def get_chat_suggestions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatSuggestionsResponse]:
    """Retrieve suggested starter prompts, popular queries, and role-based questions."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_suggestions(company_id=company_id)
    return APIResponse[ChatSuggestionsResponse](
        success=True,
        message="Chat suggestions fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Submit Chat Response Feedback",
)
async def submit_chat_feedback(
    payload: ChatFeedbackRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[dict]:
    """Submit rating and feedback for AI chat answer."""
    company_id = get_company_id_from_claims(claims)
    data = await service.save_feedback(payload=payload)
    return APIResponse[dict](
        success=True,
        message="Feedback saved successfully.",
        data=data,
        errors=None,
    )

