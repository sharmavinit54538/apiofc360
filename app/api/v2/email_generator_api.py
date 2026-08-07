"""API v2 router for the AI Email Generator Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.email_generator_service import EmailGeneratorService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/emails", tags=["AI Email Generator v2"])


# Requests
class GenerateEmailRequest(BaseModel):
    company_id: uuid.UUID
    recipient_email: str = Field(..., description="Target email recipient address")
    email_type: str = Field(..., description="OFFER_LETTER | REJECTION | PROMOTION | LEAVE_APPROVAL | LEAVE_REJECTION | WARNING_LETTER | HR_ANNOUNCEMENT | BIRTHDAY_WISHES | ANNIVERSARY_WISHES | MEETING_INVITE | REMINDER_EMAIL | PERFORMANCE_FEEDBACK")
    tone: str = Field("PROFESSIONAL", description="PROFESSIONAL | FRIENDLY | FORMAL | CORPORATE")
    context_inputs: dict[str, Any] = Field(default_factory=dict, description="Metadata tags details like candidate name, dates, etc.")
    model: Optional[str] = None


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Dynamically generate and log custom emails",
)
async def generate_email(
    body: GenerateEmailRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generates custom corporate correspondence drafts in the requested tone and registers audit log logs."""
    service = EmailGeneratorService(db)
    email_log = await service.generate_and_log_email(
        company_id=body.company_id,
        recipient_email=body.recipient_email,
        email_type=body.email_type,
        tone=body.tone,
        context_inputs=body.context_inputs,
        model=body.model
    )

    return APIResponse[dict](
        success=True,
        message="Email generated and logged successfully.",
        data={
            "log_id": str(email_log.id),
            "recipient_email": email_log.recipient_email,
            "email_type": email_log.email_type,
            "tone": email_log.tone,
            "subject": email_log.subject,
            "body": email_log.body,
        },
        errors=None
    )
