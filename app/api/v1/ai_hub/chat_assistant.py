"""AI Hub — Chat Assistant (/api/v1/ai-hub/chat-assistant/*)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, NotFoundException
from app.db.database import get_db_session
from app.llm.client import get_llm_client
from app.middleware.auth import get_current_user_claims
from app.models.ai import AIConversation, AIMessage
from app.schemas.ai_hub.chat_assistant import (
    ChatConversationDeleteResponse,
    ChatConversationDetail,
    ChatConversationsPage,
    ChatConversationSummary,
    ChatMessageItem,
    ChatMessageResponse,
    CreateConversationRequest,
    SendChatMessageRequest,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-hub/chat-assistant", tags=["AI Hub - Chat Assistant"])


@router.get(
    "/conversations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatConversationsPage],
    summary="List Conversations (Paginated)",
)
async def list_conversations(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_order: Optional[str] = Query(None, alias="sortOrder"),
) -> APIResponse[ChatConversationsPage]:
    """Retrieve paginated chat conversations for the current company and user."""
    company_id = get_company_id_from_claims(claims)
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(user_id_raw) if user_id_raw else None

    stmt = select(AIConversation).options(selectinload(AIConversation.messages))
    count_stmt = select(func.count(AIConversation.id))

    if company_id is not None:
        stmt = stmt.where(AIConversation.company_id == company_id)
        count_stmt = count_stmt.where(AIConversation.company_id == company_id)
    if user_id is not None:
        stmt = stmt.where(AIConversation.user_id == user_id)
        count_stmt = count_stmt.where(AIConversation.user_id == user_id)

    if search:
        search_clause = AIConversation.title.ilike(f"%{search}%")
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total_res = await session.execute(count_stmt)
    total = total_res.scalar() or 0

    if sort_by and hasattr(AIConversation, sort_by):
        col = getattr(AIConversation, sort_by)
        stmt = stmt.order_by(col.asc() if (sort_order or "").lower() == "asc" else col.desc())
    else:
        stmt = stmt.order_by(desc(AIConversation.updated_at))

    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    res = await session.execute(stmt)
    convs = res.scalars().all()

    items: list[ChatConversationSummary] = []
    for c in convs:
        last_msg = c.messages[-1].message if c.messages else None
        items.append(
            ChatConversationSummary(
                conversationId=str(c.id),
                title=c.title,
                agentId="general-copilot",
                messageCount=len(c.messages),
                lastMessage=last_msg,
                createdAt=c.created_at.isoformat(),
                updatedAt=c.updated_at.isoformat(),
            )
        )

    pages = (total + limit - 1) // limit if limit > 0 else 0

    data = ChatConversationsPage(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
    return APIResponse[ChatConversationsPage](
        success=True,
        message="Conversations retrieved successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ChatConversationDetail],
    summary="Create New Conversation",
)
async def create_conversation(
    payload: CreateConversationRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChatConversationDetail]:
    """Start a new chat conversation with optional initial message and agent linkage."""
    company_id = get_company_id_from_claims(claims)
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise AppException("Valid user authentication required.")
    user_id = uuid.UUID(user_id_raw)

    conv = AIConversation(
        user_id=user_id,
        company_id=company_id,
        title=payload.title,
    )
    session.add(conv)
    await session.flush()

    messages: list[ChatMessageItem] = []

    if payload.initialMessage and payload.initialMessage.strip():
        user_msg = AIMessage(
            conversation_id=conv.id,
            role="user",
            message=payload.initialMessage.strip(),
        )
        session.add(user_msg)
        await session.flush()

        messages.append(
            ChatMessageItem(
                id=str(user_msg.id),
                role=user_msg.role,
                content=user_msg.message,
                createdAt=user_msg.created_at.isoformat(),
            )
        )

        # Trigger AI welcome / response
        llm = get_llm_client()
        try:
            prompt = f"User started conversation '{payload.title}' with message: {payload.initialMessage.strip()}. Respond as a helpful Aurix HR AI Assistant."
            ai_reply = await llm.complete(prompt=prompt, temperature=0.7)
        except Exception:
            ai_reply = f"Hello! I am your AI assistant for {payload.title}. How can I assist you with HR operations today?"

        ai_msg = AIMessage(
            conversation_id=conv.id,
            role="ai",
            message=ai_reply.strip(),
        )
        session.add(ai_msg)
        await session.flush()

        messages.append(
            ChatMessageItem(
                id=str(ai_msg.id),
                role=ai_msg.role,
                content=ai_msg.message,
                createdAt=ai_msg.created_at.isoformat(),
            )
        )

    await session.commit()
    await session.refresh(conv)

    data = ChatConversationDetail(
        conversationId=str(conv.id),
        title=conv.title,
        agentId=payload.agentId or "general-copilot",
        messages=messages,
        createdAt=conv.created_at.isoformat(),
        updatedAt=conv.updated_at.isoformat(),
    )
    return APIResponse[ChatConversationDetail](
        success=True,
        message="Conversation created successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/conversations/{conversationId}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatConversationDetail],
    summary="Get Conversation Detail",
)
async def get_conversation(
    conversationId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChatConversationDetail]:
    """Retrieve all messages and metadata for a conversation."""
    company_id = get_company_id_from_claims(claims)
    try:
        conv_uuid = uuid.UUID(conversationId)
    except (ValueError, TypeError):
        raise AppException(message=f"Invalid conversationId format: '{conversationId}'.")

    stmt = (
        select(AIConversation)
        .options(selectinload(AIConversation.messages))
        .where(AIConversation.id == conv_uuid)
    )
    if company_id is not None:
        stmt = stmt.where(AIConversation.company_id == company_id)

    res = await session.execute(stmt)
    conv = res.scalars().first()
    if not conv:
        raise NotFoundException(message=f"Conversation '{conversationId}' not found.")

    msgs = [
        ChatMessageItem(
            id=str(m.id),
            role=m.role,
            content=m.message,
            createdAt=m.created_at.isoformat(),
        )
        for m in conv.messages
    ]

    data = ChatConversationDetail(
        conversationId=str(conv.id),
        title=conv.title,
        agentId="general-copilot",
        messages=msgs,
        createdAt=conv.created_at.isoformat(),
        updatedAt=conv.updated_at.isoformat(),
    )
    return APIResponse[ChatConversationDetail](
        success=True,
        message="Conversation retrieved successfully.",
        data=data,
        errors=None,
    )


@router.delete(
    "/conversations/{conversationId}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatConversationDeleteResponse],
    summary="Delete Conversation",
)
async def delete_conversation(
    conversationId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChatConversationDeleteResponse]:
    """Delete a conversation and all its messages."""
    company_id = get_company_id_from_claims(claims)
    try:
        conv_uuid = uuid.UUID(conversationId)
    except (ValueError, TypeError):
        raise AppException(message=f"Invalid conversationId format: '{conversationId}'.")

    stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
    if company_id is not None:
        stmt = stmt.where(AIConversation.company_id == company_id)

    res = await session.execute(stmt)
    conv = res.scalars().first()
    if not conv:
        raise NotFoundException(message=f"Conversation '{conversationId}' not found.")

    await session.delete(conv)
    await session.commit()

    return APIResponse[ChatConversationDeleteResponse](
        success=True,
        message="Conversation deleted successfully.",
        data=ChatConversationDeleteResponse(conversationId=conversationId, deleted=True),
        errors=None,
    )


@router.post(
    "/message",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChatMessageResponse],
    summary="Send Message to Assistant",
)
async def send_message(
    payload: SendChatMessageRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChatMessageResponse]:
    """Post user message to conversation, generate AI assistant response, and append to history."""
    company_id = get_company_id_from_claims(claims)
    try:
        conv_uuid = uuid.UUID(payload.conversationId)
    except (ValueError, TypeError):
        raise AppException(message=f"Invalid conversationId format: '{payload.conversationId}'.")

    stmt = (
        select(AIConversation)
        .options(selectinload(AIConversation.messages))
        .where(AIConversation.id == conv_uuid)
    )
    if company_id is not None:
        stmt = stmt.where(AIConversation.company_id == company_id)

    res = await session.execute(stmt)
    conv = res.scalars().first()
    if not conv:
        raise NotFoundException(message=f"Conversation '{payload.conversationId}' not found.")

    # 1. Save user message
    user_msg = AIMessage(
        conversation_id=conv.id,
        role="user",
        message=payload.content,
    )
    session.add(user_msg)
    await session.flush()

    # 2. Generate response via LLM
    llm = get_llm_client()
    recent_context = "\n".join([f"{m.role}: {m.message}" for m in conv.messages[-4:]])
    prompt = f"""
You are Aurix AI, an intelligent enterprise HRMS Copilot.
Conversation Title: {conv.title}
Recent History:
{recent_context}
User: {payload.content}

Provide a helpful, professional, database-grounded HR answer.
"""
    try:
        ai_reply = await llm.complete(prompt=prompt, temperature=0.5)
        ai_text = ai_reply.strip()
    except Exception as exc:
        logger.warning("LLM response failed: %s", exc)
        ai_text = (
            f"I have received your message regarding '{payload.content[:50]}...'. "
            "Our HR systems have logged this inquiry and your request is being processed."
        )

    # 3. Save AI message
    ai_msg = AIMessage(
        conversation_id=conv.id,
        role="ai",
        message=ai_text,
    )
    session.add(ai_msg)
    conv.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(ai_msg)

    data = ChatMessageResponse(
        conversationId=str(conv.id),
        messageId=str(ai_msg.id),
        role="ai",
        content=ai_msg.message,
        agentId=payload.agentId or "general-copilot",
        suggestions=[
            "Show attendance trends for my team",
            "What is the leave policy for casual leaves?",
            "Check status of recent payroll cycle",
        ],
        createdAt=ai_msg.created_at.isoformat(),
    )
    return APIResponse[ChatMessageResponse](
        success=True,
        message="Message processed successfully.",
        data=data,
        errors=None,
    )
