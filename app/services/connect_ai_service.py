"""AI Communication Copilot service for OFC360 Connect."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import status

from app.core.exceptions import AppException
from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class ConnectAIService:
    """Provides real-time AI transformations for text, tones, replies, and summaries."""

    def __init__(self) -> None:
        self.llm = get_llm_client()

    async def transform_text(
        self,
        text: str,
        action: Literal["professional", "generate_reply", "tone", "shorten", "expand", "summarize"],
        tone: Literal["friendly", "diplomatic", "urgent"] | None = None,
        context: str | None = None,
    ) -> str:
        """Transform user message using OFC360 LLM with fallback handling and rate limits."""
        if not text or not text.strip():
            raise AppException(message="Text cannot be empty.", status_code=status.HTTP_400_BAD_REQUEST)

        # Build prompt based on action
        system_prompt = (
            "You are OFC360 Connect AI Copilot, an expert corporate communication assistant. "
            "Your output must be only the transformed text itself, without introductory pleasantries, quotes, or markdown explanations."
        )

        user_prompt = ""
        if action == "professional":
            user_prompt = (
                f"Rewrite the following text into clear, polite, and professional corporate workplace English:\n\n{text}"
            )
        elif action == "generate_reply":
            ctx = f"Context of previous conversation: {context}\n\n" if context else ""
            user_prompt = (
                f"{ctx}Generate a helpful, constructive, and professional response to this message:\n\n{text}"
            )
        elif action == "tone":
            target_tone = tone or "friendly"
            user_prompt = (
                f"Rewrite the following message using a distinct '{target_tone}' tone while keeping the original intent:\n\n{text}"
            )
        elif action == "shorten":
            user_prompt = (
                f"Condense the following message to be concise, direct, and brief while retaining all essential facts:\n\n{text}"
            )
        elif action == "expand":
            user_prompt = (
                f"Expand the following brief notes/message into a well-structured, clear, and comprehensive message:\n\n{text}"
            )
        elif action == "summarize":
            user_prompt = (
                f"Summarize the key takeaways and action items of the following text:\n\n{text}"
            )
        else:
            raise AppException(message=f"Unsupported action '{action}'.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                num_predict=1024,
            )
            result = response.strip()
            if result:
                return result
        except Exception as e:
            err_str = str(e).lower()
            if "rate limit" in err_str or "429" in err_str or "too many requests" in err_str:
                logger.warning("AI Copilot hit provider rate limit: %s", e)
                raise AppException(
                    message="AI Copilot rate limit reached. Please try again shortly.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                ) from e
            logger.warning("LLM call failed or unavailable in Connect AI: %s. Using heuristic fallback.", e)

        # High quality heuristic fallback for local/offline resilience
        return self._heuristic_fallback(text, action, tone)

    def _heuristic_fallback(
        self,
        text: str,
        action: str,
        tone: str | None = None,
    ) -> str:
        """Provide a clean fallback response when LLM backend is offline."""
        cleaned = text.strip()
        if action == "professional":
            return f"Dear Team, {cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned}. Thank you for your continued collaboration."
        elif action == "generate_reply":
            return f"Thank you for the update. I have reviewed the details regarding '{cleaned[:60]}...' and will follow up with next steps shortly."
        elif action == "tone":
            if tone == "friendly":
                return f"Hi there! Just wanted to share: {cleaned} Looking forward to connecting soon! 😊"
            elif tone == "diplomatic":
                return f"Thank you for sharing your perspectives. Regarding this matter: {cleaned} Let us align on the best path forward."
            elif tone == "urgent":
                return f"URGENT ATTENTION REQUIRED: {cleaned} Please address this as top priority."
            return cleaned
        elif action == "shorten":
            sentences = [s.strip() for s in cleaned.split(".") if s.strip()]
            return sentences[0] + "." if sentences else cleaned
        elif action == "expand":
            return f"Regarding our recent discussion on this subject:\n\n{cleaned}\n\nPlease let me know if any further clarification or documentation is required."
        elif action == "summarize":
            return f"Summary of points:\n• {cleaned}"
        return cleaned


_connect_ai_service = ConnectAIService()


def get_connect_ai_service() -> ConnectAIService:
    return _connect_ai_service
