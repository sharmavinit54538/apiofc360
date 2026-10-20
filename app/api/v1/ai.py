"""AI Chat Assistant API endpoints."""

import logging
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
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Chat Assistant"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="AI Assistant health check (admin/super-admin only)",
)
async def ai_health(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> APIResponse[dict]:
    """Health check for AI Assistant: Ollama connectivity, model availability, DB status.
    Restricted to admin/super-admin roles.
    """
    role = claims.get("role", "").lower()
    is_admin = role in {"admin", "hr_admin", "super_admin", "SUPER_ADMIN"} or claims.get("is_super_admin")
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for AI health check.",
        )

    from app.llm.client import get_llm_client
    from sqlalchemy import text
    from app.db.database import engine

    request_id = uuid.uuid4().hex[:8]
    base_url = settings.OLLAMA_BASE_URL
    host_only = base_url.replace("http://", "").replace("https://", "").split(":")[0] if base_url else "unknown"
    
    # Check Ollama
    ollama_reachable = False
    installed_models = []
    configured_models = {
        "sql": getattr(settings, "AI_SQL_MODEL", settings.OLLAMA_MODEL),
        "answer": getattr(settings, "AI_ANSWER_MODEL", settings.OLLAMA_MODEL),
    }
    models_missing = []
    last_error = None
    
    try:
        llm_client = get_llm_client()
        health = await llm_client.check_health()
        ollama_reachable = health.get("healthy", False)
        installed_models = health.get("models", [])
        
        # Check configured models
        for model in configured_models.values():
            if model and model not in installed_models:
                model_base = model.split(":")[0]
                if not any(m.split(":")[0] == model_base for m in installed_models):
                    models_missing.append(model)
    except Exception as e:
        last_error = str(e)
        logger.error("AI health check Ollama error (req_id=%s): %s", request_id, e)

    # Check DB
    db_ok = False
    schema_tables_loaded = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
        # Check if schema cache has tables loaded
        from app.services.ai_service import schema_cache
        schema_tables_loaded = bool(schema_cache.tables)
    except Exception as e:
        last_error = last_error or str(e)
        logger.error("AI health check DB error (req_id=%s): %s", request_id, e)

    return APIResponse[dict](
        success=True,
        message="AI health check completed.",
        data={
            "ollama_reachable": ollama_reachable,
            "base_url": host_only,
            "installed_models": installed_models,
            "configured_models": configured_models,
            "models_missing": models_missing,
            "db_ok": db_ok,
            "schema_tables_loaded": schema_tables_loaded,
            "last_error": last_error,
        },
        errors=None,
    )


@router.post(
    "/chat",
    summary="Send a message to the AI Chat Assistant (Streaming)",
)
async def chat_message(
    payload: ChatRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> StreamingResponse:
    """Send a query to OFC HR AI, streaming database-grounded response details chunk by chunk."""
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
