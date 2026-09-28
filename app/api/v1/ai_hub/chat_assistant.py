"""AI Hub — Chat Assistant Gateway (/api/v1/ai-hub/chat-assistant/*).

COMPATIBILITY ROUTER:
This router delegates to ChatAssistantService (/api/v1/ai/chat/*)
to ensure backward compatibility for frontend clients (e.g. aiHub.api.ts)
until they are updated to the canonical /api/v1/ai/chat/* paths.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.chat_assistant import (
    ChatAssistantRequest,
    ChatAssistantResponse,
    ChatHistoryResponse,
    CreateConversationRequest,
)
from app.api.v1.chat_assistant import get_company_id_from_claims, get_chat_service
from app.services.chat_assistant_service import ChatAssistantService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-hub/chat-assistant", tags=["AI Hub - Chat Assistant (Compatibility)"])


@router.get(
    "/conversations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatHistoryResponse],
    summary="List Conversations (Compatibility)",
)
async def list_conversations(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatHistoryResponse]:
    """Retrieve chat conversations for the current company and user."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history(company_id=company_id)
    return APIResponse[ChatHistoryResponse](
        success=True,
        message="Conversations retrieved successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Create New Conversation (Compatibility)",
)
async def create_conversation(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
    payload: Optional[CreateConversationRequest] = Body(None),
) -> APIResponse[ChatAssistantResponse]:
    """Start a new chat conversation with optional initial message and agent linkage."""
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


@router.get(
    "/conversations/{conversationId}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Get Conversation Detail (Compatibility)",
)
async def get_conversation(
    conversationId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Retrieve details and messages for a conversation."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history_detail(conversation_id=conversationId, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="Conversation retrieved successfully.",
        data=data,
        errors=None,
    )


@router.delete(
    "/conversations/{conversationId}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Delete Conversation (Compatibility)",
)
async def delete_conversation(
    conversationId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[dict]:
    """Delete a conversation and all its messages."""
    company_id = get_company_id_from_claims(claims)
    data = await service.delete_history(conversation_id=conversationId, company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="Conversation deleted successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/message",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatAssistantResponse],
    summary="Send Message to Assistant (Compatibility)",
)
async def send_message(
    payload: ChatAssistantRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ChatAssistantService, Depends(get_chat_service)],
) -> APIResponse[ChatAssistantResponse]:
    """Post user message to conversation, generate AI assistant response with LLM + RAG."""
    company_id = get_company_id_from_claims(claims)
    data = await service.process_chat(request=payload, company_id=company_id)
    return APIResponse[ChatAssistantResponse](
        success=True,
        message="Message processed successfully.",
        data=data,
        errors=None,
    )
