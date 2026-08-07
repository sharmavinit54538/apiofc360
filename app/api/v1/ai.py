"""AI Chat Assistant API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import StreamingResponse

from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
    RenameRequest,
)
from app.services.ai_service import AIService, get_ai_service
from app.services.ollama_client import ollama_client

router = APIRouter(prefix="/ai", tags=["AI Chat Assistant"])


@router.post(
    "/chat",
    summary="Send a message to the AI Chat Assistant (Streaming)",
)
async def chat_message(
    payload: ChatRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> StreamingResponse:
    """Send a query to Aurix AI, streaming database-grounded response details chunk by chunk."""
    user_id = uuid.UUID(claims.get("sub"))
    co_id_str = claims.get("company_id")
    company_id = uuid.UUID(co_id_str) if co_id_str else None

    # Error Handling: Check if Ollama is running, else return 503
    is_healthy = await ollama_client.check_health()
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama AI model server is offline/unavailable.",
        )

    generator = service.send_message_stream(
        user_id=user_id,
        company_id=company_id,
        message=payload.message,
        conversation_id=payload.conversation_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[ConversationSummary]],
    summary="Get user conversation list",
)
async def get_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[list[ConversationSummary]]:
    """Retrieve all past chat conversations for the authorized user."""
    user_id = uuid.UUID(claims.get("sub"))
    history = await service.get_history(user_id)
    return APIResponse[list[ConversationSummary]](
        success=True,
        message="Conversation history retrieved successfully.",
        data=history,
        errors=None,
    )


@router.get(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ConversationDetail],
    summary="Get conversation detail",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[ConversationDetail]:
    """Retrieve full message logs for a single chat conversation."""
    user_id = uuid.UUID(claims.get("sub"))
    detail = await service.get_conversation(user_id, conversation_id)
    return APIResponse[ConversationDetail](
        success=True,
        message="Conversation detail retrieved successfully.",
        data=detail,
        errors=None,
    )


@router.patch(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ConversationSummary],
    summary="Rename conversation title",
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: RenameRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[ConversationSummary]:
    """Change the title of an existing conversation."""
    user_id = uuid.UUID(claims.get("sub"))
    updated = await service.rename_conversation(user_id, conversation_id, payload.title)
    return APIResponse[ConversationSummary](
        success=True,
        message="Conversation title updated successfully.",
        data=updated,
        errors=None,
    )


@router.delete(
    "/history/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete conversation session",
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[None]:
    """Delete a single chat conversation and its messages."""
    user_id = uuid.UUID(claims.get("sub"))
    await service.delete_conversation(user_id, conversation_id)
    return APIResponse[None](
        success=True,
        message="Conversation deleted successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/clear",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Clear all conversations",
)
async def clear_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[None]:
    """Clear all chat history logs for the current user."""
    user_id = uuid.UUID(claims.get("sub"))
    await service.clear_history(user_id)
    return APIResponse[None](
        success=True,
        message="All chat history cleared successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[str]],
    summary="Get dynamic AI prompt suggestions",
)
async def get_suggestions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> APIResponse[list[str]]:
    """Retrieve suggested queries based on real-time workforce context."""
    suggestions = await service.get_suggestions()
    return APIResponse[list[str]](
        success=True,
        message="Dynamic query suggestions retrieved.",
        data=suggestions,
        errors=None,
    )
