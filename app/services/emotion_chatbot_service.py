"""AI Emotion Aware Chatbot service.

Handles classification of employee sentiment (Angry, Sad, Happy, etc.) and
calibrates empathetic replies.
"""

from __future__ import annotations

import logging
import json
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.emotion_chatbot import (
    EmotionAwareChatSession,
    EmotionAwareChatMessage,
)

logger = logging.getLogger(__name__)


class EmotionChatbotService:
    """Enterprise AI Emotion Aware HR Chatbot Service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def start_chat_session(
        self,
        company_id: uuid.UUID,
        employee_id: str,
    ) -> EmotionAwareChatSession:
        """Register a chat session for an employee.

        Args:
            company_id: The tenant UUID.
            employee_id: The human-readable employee code, e.g. ``AUR-EMP-0105``.
                         This is the ``employee_id`` string column, NOT the UUID primary key.
        """
        # Look up by the human-readable employee_id code (e.g. "AUR-EMP-0105")
        emp_stmt = select(Employee).where(Employee.employee_id == employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalar_one_or_none()
        if not emp:
            raise ValueError(f"Employee with ID '{employee_id}' not found.")

        session = EmotionAwareChatSession(
            id=uuid.uuid4(),
            company_id=company_id,
            employee_id=employee_id,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Emotion aware chat session started: %s for employee %s", session.id, employee_id)
        return session

    async def post_chat_message(
        self,
        session_id: uuid.UUID,
        sender_role: str,  # USER, SYSTEM
        message_text: str,
        model: Optional[str] = None,
    ) -> EmotionAwareChatMessage:
        """Post a dialogue entry and return chatbot response matching the classified emotion state."""
        role = sender_role.upper()
        if role not in ("USER", "SYSTEM"):
            raise ValueError("Role must be USER or SYSTEM.")

        # Save user message
        msg = EmotionAwareChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            sender_role=role,
            message_text=message_text,
            detected_emotion="NEUTRAL",
        )
        self.db.add(msg)
        await self.db.flush()

        if role == "USER":
            # Retrieve recent conversation log history
            history_stmt = (
                select(EmotionAwareChatMessage)
                .where(EmotionAwareChatMessage.session_id == session_id)
                .order_by(EmotionAwareChatMessage.created_at.asc())
            )
            hist_res = await self.db.execute(history_stmt)
            history = hist_res.scalars().all()

            lines = []
            for h in history[:-1]:  # exclude current message
                lines.append(f"{h.sender_role}: {h.message_text}")
            history_str = "\n".join(lines) or "No history logs yet."

            try:
                prompt = PromptLibrary.ai_emotion_chatbot_user(history_str, message_text)
                res_text = await self.llm.complete(
                    prompt=prompt,
                    system=PromptLibrary.AI_EMOTION_AWARE_CHAT,
                    model=model,
                    json_mode=True,
                    temperature=0.4
                )
                eval_data = ResponseParser.extract_json_object(res_text)
            except Exception as exc:
                logger.error("AI Emotion Chatbot completion failed: %s", exc)
                eval_data = {
                    "detected_emotion": "NEUTRAL",
                    "reply_text": "I am here to support you. Please tell me more."
                }

            # Update user message classified emotion label
            msg.detected_emotion = eval_data.get("detected_emotion", "NEUTRAL").upper()

            # Save chatbot adjusted response
            reply = EmotionAwareChatMessage(
                id=uuid.uuid4(),
                session_id=session_id,
                sender_role="SYSTEM",
                message_text=eval_data.get("reply_text", ""),
                detected_emotion="NEUTRAL",
            )
            self.db.add(reply)
            await self.db.commit()
            await self.db.refresh(reply)
            return reply

        await self.db.commit()
        await self.db.refresh(msg)
        return msg
