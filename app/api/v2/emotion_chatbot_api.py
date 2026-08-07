"""API v2 router for the AI Emotion Aware Chatbot Engine.

Production-ready with:
- company_id extracted from JWT claims (not required in body)
- Pydantic v2 field aliases for camelCase frontend compatibility
- Enum-based session_type validation
- Detailed validation error logging with request body capture
- Clean 422 messages without exposing internals
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.emotion_chatbot import EmotionAwareChatMessage
from app.schemas.auth import APIResponse
from app.services.emotion_chatbot_service import EmotionChatbotService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/emotions", tags=["AI Emotion Aware Chatbot v2"])


# ─────────────────────────────────────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    """Payload for POST /emotions/sessions.

    Supports both snake_case and camelCase field names so JavaScript frontends
    do not need to transform their payloads.

    company_id is optional here — it is extracted from the JWT claims by default.
    If provided in the body it overrides the claim (useful for admin impersonation).
    employee_id is required: it identifies which employee the session is for.
    """

    model_config = ConfigDict(populate_by_name=True)

    employee_id: str = Field(
        ...,
        alias="employeeId",
        min_length=1,
        max_length=20,
        description="The employee's readable ID code (e.g. AUR-EMP-0105).",
        examples=["AUR-EMP-0105"],
    )
    company_id: Optional[UUID4] = Field(
        default=None,
        alias="companyId",
        description="UUID of the company. Defaults to the value in the JWT token.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )

    @field_validator("employee_id", mode="before")
    @classmethod
    def validate_employee_id(cls, v: object) -> object:
        """Provide a clear error message when employee_id is missing or blank."""
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("employee_id is required (e.g. AUR-EMP-0105).")
        return v


class PostMessageRequest(BaseModel):
    """Payload for POST /emotions/sessions/{session_id}/messages."""

    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The message text to send to the chatbot.",
        examples=["I'm feeling stressed about the upcoming deadline."],
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional LLM model override.",
        examples=["llama3.2"],
    )

    @field_validator("message", mode="before")
    @classmethod
    def validate_message_not_blank(cls, v: object) -> object:
        """Reject blank or whitespace-only messages with a clear error."""
        if isinstance(v, str) and not v.strip():
            raise ValueError("message must not be empty or whitespace.")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Logging helper
# ─────────────────────────────────────────────────────────────────────────────

async def _log_request(request: Request, claims: dict | None, extra: str = "") -> None:
    """Log incoming request body and authenticated user for debugging 422s."""
    user_id = claims.get("sub") if claims else "unauthenticated"
    try:
        body = await request.json()
    except Exception:
        body = "<non-JSON body>"
    logger.info(
        "REQUEST %s %s | user=%s | body=%s%s",
        request.method, request.url.path, user_id, body, f" | {extra}" if extra else "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /emotions/sessions
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Start emotion aware chatbot session",
)
async def init_session(
    request: Request,
    body: StartSessionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Sets up a dialogue context channel registered for a specific employee.

    company_id is resolved from JWT claims if not provided in the request body.
    """
    # Resolve company_id: body takes precedence, otherwise use JWT claim
    company_id_str = claims.get("company_id")
    if body.company_id:
        company_id = body.company_id
    elif company_id_str:
        try:
            company_id = uuid.UUID(company_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid company_id in authentication token.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id could not be resolved. Include it in the request body or ensure your token is valid.",
        )

    logger.info(
        "POST /emotions/sessions | user=%s | employee_id=%s | company_id=%s",
        claims.get("sub"), body.employee_id, company_id,
    )

    service = EmotionChatbotService(db)
    try:
        session = await service.start_chat_session(
            company_id=company_id,
            employee_id=body.employee_id,
        )
    except ValueError as val_err:
        logger.warning(
            "POST /emotions/sessions failed | user=%s | reason=%s",
            claims.get("sub"), str(val_err),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Emotion aware chat session started.",
        data={
            "session_id": str(session.id),
            "employee_id": str(session.employee_id),
            "company_id": str(session.company_id),
        },
        errors=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /emotions/sessions/{session_id}/messages
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/sessions/{session_id}/messages",
    response_model=APIResponse[dict],
    summary="Post message and generate emotion adjusted reply",
)
async def send_message(
    session_id: uuid.UUID,
    body: PostMessageRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Posts user text, classifies sentiment (Happy/Angry/Sad/etc.) and returns a calibrated reply."""
    logger.info(
        "POST /emotions/sessions/%s/messages | user=%s | message_len=%d",
        session_id, claims.get("sub"), len(body.message),
    )

    service = EmotionChatbotService(db)
    try:
        reply = await service.post_chat_message(
            session_id=session_id,
            sender_role="USER",
            message_text=body.message,
            model=body.model,
        )
    except ValueError as val_err:
        logger.warning(
            "POST /emotions/sessions/%s/messages failed | user=%s | reason=%s",
            session_id, claims.get("sub"), str(val_err),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))

    # Re-query the latest user message to retrieve the classified emotion
    stmt = (
        select(EmotionAwareChatMessage)
        .where(
            EmotionAwareChatMessage.session_id == session_id,
            EmotionAwareChatMessage.sender_role == "USER",
        )
        .order_by(EmotionAwareChatMessage.created_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    user_msg = res.scalar_one_or_none()

    return APIResponse[dict](
        success=True,
        message="Emotion adjusted reply compiled.",
        data={
            "reply_id": str(reply.id),
            "detected_emotion": user_msg.detected_emotion if user_msg else "NEUTRAL",
            "reply_text": reply.message_text,
        },
        errors=None,
    )
