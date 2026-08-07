"""Employee Mental Wellness AI services.

Manages daily check-ins, HR wellness escalation rules, secure anonymous chat sessions,
and local LLM-based sentiment and stress coaching.
"""

from __future__ import annotations

import logging
import json
import uuid
import random
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.wellness import (
    EmployeeWellnessLog,
    WellnessEscalationRule,
    WellnessAnonymousChatSession,
    WellnessAnonymousChatMessage,
)

logger = logging.getLogger(__name__)


ANONYMOUS_ALIASES = [
    "Calm Koala", "Serene Swan", "Peaceful Panda", "Tranquil Turtle",
    "Gentle Giraffe", "Happy Otter", "Wise Owl", "Friendly Fox"
]


class WellnessService:
    """Enterprise Employee Wellness coaching service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def log_wellness_checkin(
        self,
        employee_id: uuid.UUID,
        mood_score: int,
        stress_level: str,
        sleep_hours: Decimal,
    ) -> EmployeeWellnessLog:
        """Record daily wellness metrics and check for burnout/HR escalations."""
        # Query employee to get company_id
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalar_one_or_none()
        if not emp:
            raise ValueError("Employee not found.")

        # Simple burnout heuristic
        burnout = (mood_score <= 3 and stress_level.upper() == "HIGH")

        # Save check-in
        log = EmployeeWellnessLog(
            id=uuid.uuid4(),
            employee_id=employee_id,
            mood_score=mood_score,
            stress_level=stress_level.upper(),
            sleep_hours=sleep_hours,
            burnout_detected=burnout,
            logged_at=date.today(),
        )
        self.db.add(log)
        await self.db.flush()

        # Run Escalation rules
        if emp.company_id:
            rules_stmt = select(WellnessEscalationRule).where(
                WellnessEscalationRule.company_id == emp.company_id
            )
            rules_res = await self.db.execute(rules_stmt)
            rules = rules_res.scalars().all()

            for rule in rules:
                mood_breached = mood_score <= rule.min_mood_score
                stress_breached = stress_level.upper() == rule.stress_trigger_level.upper()

                if mood_breached or stress_breached:
                    logger.warning(
                        "WELLNESS ESCALATION ALERT: Employee %s breached criteria parameters. "
                        "Action: %s. Notifying: %s",
                        emp.employee_id, rule.action_type, rule.recipient_email
                    )

        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def create_anonymous_chat_session(
        self,
        company_id: uuid.UUID,
    ) -> WellnessAnonymousChatSession:
        """Register a secure chat room with a random alias pseudonym."""
        alias = random.choice(ANONYMOUS_ALIASES) + f" {random.randint(10, 99)}"
        session = WellnessAnonymousChatSession(
            id=uuid.uuid4(),
            company_id=company_id,
            alias_name=alias,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Anonymous wellness chat session created: %s (%s)", session.id, alias)
        return session

    async def send_chat_message(
        self,
        session_id: uuid.UUID,
        sender_role: str,  # USER, COACH
        message_text: str,
        model: Optional[str] = None,
    ) -> WellnessAnonymousChatMessage:
        """Log chat message and run AI coaching completion if user posts."""
        role = sender_role.upper()
        if role not in ("USER", "COACH"):
            raise ValueError("Sender role must be USER or COACH.")

        # Save user message
        msg = WellnessAnonymousChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            sender_role=role,
            message_text=message_text,
            sentiment_score=Decimal("0.00"),
        )
        self.db.add(msg)
        await self.db.flush()

        if role == "USER":
            # Retrieve recent dialogue history
            history_stmt = (
                select(WellnessAnonymousChatMessage)
                .where(WellnessAnonymousChatMessage.session_id == session_id)
                .order_by(WellnessAnonymousChatMessage.created_at.asc())
            )
            hist_res = await self.db.execute(history_stmt)
            history = hist_res.scalars().all()

            lines = []
            for h in history[:-1]:  # exclude current message
                lines.append(f"{h.sender_role}: {h.message_text}")
            history_str = "\n".join(lines) or "No history logs yet."

            try:
                prompt = PromptLibrary.ai_wellness_coach_user(history_str, message_text)
                res_text = await self.llm.complete(
                    prompt=prompt,
                    system=PromptLibrary.AI_WELLNESS_COACH_CHAT,
                    model=model,
                    json_mode=True,
                    temperature=0.4
                )
                eval_data = ResponseParser.extract_json_object(res_text)
            except Exception as exc:
                logger.error("AI Wellness Coach completion failed: %s", exc)
                eval_data = {
                    "sentiment_score": 0.00,
                    "stress_detected": False,
                    "coach_response": "Thank you for sharing that with me. I am here to listen whenever you're ready."
                }

            # Update user message sentiment score
            msg.sentiment_score = Decimal(str(eval_data.get("sentiment_score", 0.00)))

            # Save AI coach reply
            coach_msg = WellnessAnonymousChatMessage(
                id=uuid.uuid4(),
                session_id=session_id,
                sender_role="COACH",
                message_text=eval_data.get("coach_response", ""),
                sentiment_score=Decimal("0.00"),
            )
            self.db.add(coach_msg)
            await self.db.commit()
            await self.db.refresh(coach_msg)
            return coach_msg

        await self.db.commit()
        await self.db.refresh(msg)
        return msg
