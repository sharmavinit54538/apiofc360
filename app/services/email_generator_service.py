"""AI Email Generator service.

Orchestrates automatic email copy creation in custom tones and keeps log audits.
"""

from __future__ import annotations

import logging
import json
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.email_generator import GeneratedEmailLog

logger = logging.getLogger(__name__)


class EmailGeneratorService:
    """Enterprise AI Email Generation Service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def generate_and_log_email(
        self,
        company_id: uuid.UUID,
        recipient_email: str,
        email_type: str,  # OFFER_LETTER, REJECTION, PROMOTION, LEAVE_APPROVAL, LEAVE_REJECTION, WARNING_LETTER, HR_ANNOUNCEMENT, BIRTHDAY_WISHES, ANNIVERSARY_WISHES, MEETING_INVITE, REMINDER_EMAIL, PERFORMANCE_FEEDBACK
        tone: str,  # PROFESSIONAL, FRIENDLY, FORMAL, CORPORATE
        context_inputs: dict[str, Any],
        model: Optional[str] = None,
    ) -> GeneratedEmailLog:
        # Validate company exists to avoid database foreign key constraint violation
        from app.models.company import Company
        from app.core.exceptions import NotFoundException
        from sqlalchemy import select
        
        comp_stmt = select(Company.id).where(Company.id == company_id)
        comp_res = await self.db.execute(comp_stmt)
        if not comp_res.scalar():
            raise NotFoundException(f"Company with ID {company_id} not found.")

        # Convert context dictionary to readable key-value string for LLM
        context_lines = []
        for k, v in context_inputs.items():
            context_lines.append(f"{k}: {v}")
        context_str = "\n".join(context_lines) or "No additional context."

        try:
            prompt = PromptLibrary.ai_email_generator_user(
                email_type=email_type.upper(),
                tone=tone.upper(),
                context_details=context_str
            )
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_EMAIL_GENERATOR,
                model=model,
                json_mode=True,
                temperature=0.3
            )
            data = ResponseParser.extract_json_object(res_text)
            subject = data.get("subject", f"Update: {email_type.replace('_', ' ').title()}")
            body = data.get("body", "Please find the requested update details attached.")
        except Exception as exc:
            logger.error("AI Email generation failed: %s", exc)
            subject = f"Notification: {email_type.replace('_', ' ').title()}"
            body = "This is a standard automated notification email."

        email_log = GeneratedEmailLog(
            id=uuid.uuid4(),
            company_id=company_id,
            recipient_email=recipient_email,
            email_type=email_type.upper(),
            tone=tone.upper(),
            subject=subject,
            body=body,
        )
        self.db.add(email_log)
        await self.db.commit()
        await self.db.refresh(email_log)
        logger.info("AI email of type %s generated for %s", email_type, recipient_email)
        return email_log
