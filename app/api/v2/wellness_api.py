"""API v2 router for the Employee Mental Wellness AI Engine.

Production-ready with:
- company_id extracted from JWT claims (not required in body for most endpoints)
- Pydantic v2 field aliases for camelCase frontend compatibility
- Literal enum validation for stress_level and action_type
- EmailStr validation for recipient_email
- Detailed validation error logging
- Clear 422 error messages
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, UUID4, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.wellness import WellnessEscalationRule
from app.schemas.auth import APIResponse
from app.services.wellness_service import WellnessService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wellness", tags=["AI Wellness Coach v2"])


# ─────────────────────────────────────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────────────────────────────────────

class CheckinRequest(BaseModel):
    """Payload for POST /wellness/checkins.

    employee_id is required. company_id is resolved from JWT claims.
    Supports both snake_case and camelCase field names.
    """

    model_config = ConfigDict(populate_by_name=True)

    employee_id: UUID4 = Field(
        ...,
        alias="employeeId",
        description="UUID of the employee submitting the wellness check-in.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    mood_score: int = Field(
        ...,
        alias="moodScore",
        ge=1,
        le=10,
        description="Mood score from 1 (very low) to 10 (excellent).",
        examples=[7],
    )
    stress_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        ...,
        alias="stressLevel",
        description="Stress level category. Must be LOW, MEDIUM, or HIGH.",
        examples=["MEDIUM"],
    )
    sleep_hours: Decimal = Field(
        ...,
        alias="sleepHours",
        ge=Decimal("0"),
        le=Decimal("24"),
        description="Number of hours slept. Must be between 0 and 24.",
        examples=[Decimal("7.5")],
    )

    @field_validator("employee_id", mode="before")
    @classmethod
    def validate_employee_id(cls, v: object) -> object:
        if v is None:
            raise ValueError("employee_id is required and must be a valid UUID.")
        return v

    @field_validator("stress_level", mode="before")
    @classmethod
    def normalize_stress_level(cls, v: object) -> object:
        """Accept lowercase inputs and normalize to uppercase."""
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("sleep_hours", mode="before")
    @classmethod
    def coerce_sleep_hours(cls, v: object) -> object:
        """Accept int or float from JSON and convert to Decimal."""
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        return v


class EscalationRequest(BaseModel):
    """Payload for POST /wellness/escalation-rules.

    company_id is resolved from JWT claims if not provided in the body.
    """

    model_config = ConfigDict(populate_by_name=True)

    company_id: Optional[UUID4] = Field(
        default=None,
        alias="companyId",
        description="Company UUID. Defaults to the value from the JWT token.",
    )
    min_mood_score: int = Field(
        default=3,
        alias="minMoodScore",
        ge=1,
        le=10,
        description="Mood score threshold below which the escalation triggers.",
        examples=[3],
    )
    stress_trigger_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        default="HIGH",
        alias="stressTriggerLevel",
        description="Stress level that triggers the escalation rule.",
        examples=["HIGH"],
    )
    action_type: Literal["ALERT_HR", "SEND_EMAIL", "NOTIFY_MANAGER"] = Field(
        default="ALERT_HR",
        alias="actionType",
        description="Action to take when escalation rule is triggered.",
        examples=["ALERT_HR"],
    )
    recipient_email: EmailStr = Field(
        ...,
        alias="recipientEmail",
        description="Email address of the HR contact to notify.",
        examples=["hr@company.com"],
    )

    @field_validator("stress_trigger_level", mode="before")
    @classmethod
    def normalize_stress_trigger(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("action_type", mode="before")
    @classmethod
    def normalize_action_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().upper()
        return v


class InitChatRequest(BaseModel):
    """Payload for POST /wellness/anonymous-chats.

    company_id is optional in the body — extracted from JWT if absent.
    """

    model_config = ConfigDict(populate_by_name=True)

    company_id: Optional[UUID4] = Field(
        default=None,
        alias="companyId",
        description="Company UUID. Defaults to the value from the JWT token.",
    )


class PostMessageRequest(BaseModel):
    """Payload for POST /wellness/anonymous-chats/{session_id}/messages."""

    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Wellness coaching message text.",
        examples=["I've been feeling overwhelmed lately."],
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional LLM model override.",
        examples=["llama3.2"],
    )

    @field_validator("message", mode="before")
    @classmethod
    def validate_message_not_blank(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("message must not be empty or whitespace.")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve company_id from body or JWT
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_company_id(body_company_id: Optional[UUID4], claims: dict, endpoint: str) -> uuid.UUID:
    """Return company_id from the request body or fall back to the JWT claim."""
    if body_company_id:
        return uuid.UUID(str(body_company_id))
    company_id_str = claims.get("company_id")
    if company_id_str:
        try:
            return uuid.UUID(company_id_str)
        except ValueError:
            pass
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"company_id is required for {endpoint}. Include it in the request body or ensure your token contains a valid company_id.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /wellness/checkins
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/checkins",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Log daily employee wellness check-in",
)
async def wellness_checkin(
    body: CheckinRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Records mood, sleep and stress metrics, evaluating burnout parameters and HR alerts."""
    logger.info(
        "POST /wellness/checkins | user=%s | employee_id=%s | mood=%d | stress=%s",
        claims.get("sub"), body.employee_id, body.mood_score, body.stress_level,
    )

    service = WellnessService(db)
    try:
        log = await service.log_wellness_checkin(
            employee_id=body.employee_id,
            mood_score=body.mood_score,
            stress_level=body.stress_level,
            sleep_hours=body.sleep_hours,
        )
    except ValueError as val_err:
        logger.warning(
            "POST /wellness/checkins failed | user=%s | reason=%s",
            claims.get("sub"), str(val_err),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Wellness check-in logged successfully.",
        data={
            "log_id": str(log.id),
            "burnout_detected": log.burnout_detected,
            "logged_at": str(log.logged_at),
        },
        errors=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /wellness/escalation-rules
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/escalation-rules",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Register HR escalation rules configuration",
)
async def create_escalation_rule(
    body: EscalationRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Saves alert rules mapping critical parameters to HR contact emails."""
    company_id = _resolve_company_id(body.company_id, claims, "escalation-rules")

    logger.info(
        "POST /wellness/escalation-rules | user=%s | company_id=%s | recipient=%s",
        claims.get("sub"), company_id, body.recipient_email,
    )

    rule = WellnessEscalationRule(
        id=uuid.uuid4(),
        company_id=company_id,
        min_mood_score=body.min_mood_score,
        stress_trigger_level=body.stress_trigger_level,
        action_type=body.action_type,
        recipient_email=str(body.recipient_email),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return APIResponse[dict](
        success=True,
        message="Wellness escalation alert rule created.",
        data={
            "rule_id": str(rule.id),
            "recipient_email": rule.recipient_email,
            "action_type": rule.action_type,
        },
        errors=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /wellness/anonymous-chats
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/anonymous-chats",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create anonymous wellness coach session",
)
async def init_chat(
    body: InitChatRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Starts a secure coaching chat window assigned a random alias pseudonym."""
    company_id = _resolve_company_id(body.company_id, claims, "anonymous-chats")

    logger.info(
        "POST /wellness/anonymous-chats | user=%s | company_id=%s",
        claims.get("sub"), company_id,
    )

    service = WellnessService(db)
    session = await service.create_anonymous_chat_session(company_id)

    return APIResponse[dict](
        success=True,
        message="Anonymous wellness chat session started.",
        data={
            "session_id": str(session.id),
            "alias_name": session.alias_name,
        },
        errors=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /wellness/anonymous-chats/{session_id}/messages
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/anonymous-chats/{session_id}/messages",
    response_model=APIResponse[dict],
    summary="Post message and generate coach reply",
)
async def send_message(
    session_id: uuid.UUID,
    body: PostMessageRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Receives message text, logs user sentiment rating, and outputs AI coach replies."""
    logger.info(
        "POST /wellness/anonymous-chats/%s/messages | user=%s | message_len=%d",
        session_id, claims.get("sub"), len(body.message),
    )

    service = WellnessService(db)
    try:
        reply = await service.send_chat_message(
            session_id=session_id,
            sender_role="USER",
            message_text=body.message,
            model=body.model,
        )
    except ValueError as val_err:
        logger.warning(
            "POST /wellness/anonymous-chats/%s/messages failed | user=%s | reason=%s",
            session_id, claims.get("sub"), str(val_err),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Coach reply generated.",
        data={
            "reply_id": str(reply.id),
            "sender_role": reply.sender_role,
            "message_text": reply.message_text,
        },
        errors=None,
    )
