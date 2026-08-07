"""Conversation summarizer — compresses old conversation history using LLM.

When a conversation gets too long, older messages are summarized into a compact
representation that preserves key context while dramatically reducing token usage.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SUMMARIZE_SYSTEM = """You are a conversation summarizer for an HR AI assistant.
Compress the following conversation history into a concise summary.
Preserve: key facts, decisions made, important data points, user preferences.
Discard: greetings, filler, repeated context.
Keep the summary under 200 words. Return ONLY the summary text."""


class ConversationSummarizer:
    """Summarizes older conversation segments to free up context window space."""

    def __init__(self) -> None:
        # Import lazily to avoid circular dependencies
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from app.llm.client import get_llm_client
            self._llm = get_llm_client()
        return self._llm

    async def summarize(
        self,
        messages: list[dict[str, str]],
        max_words: int = 200,
    ) -> str:
        """Summarize a list of messages into a compact text summary.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            max_words: Target maximum words for the summary.

        Returns:
            Summary string, or empty string on failure.
        """
        if not messages:
            return ""

        # Build conversation text
        conv_text = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in messages
            if m.get("role") != "system"
        )

        if len(conv_text) < 100:
            # Too short to summarize
            return conv_text

        prompt = f"Summarize this conversation in under {max_words} words:\n\n{conv_text[:6000]}"

        try:
            llm = self._get_llm()
            summary = await llm.complete(
                prompt=prompt,
                system=_SUMMARIZE_SYSTEM,
                temperature=0.2,
                num_predict=512,
            )
            if summary:
                logger.info(
                    "Summarized %d messages (%d chars) into %d chars",
                    len(messages), len(conv_text), len(summary),
                )
                return summary.strip()
        except Exception as exc:
            logger.error("Conversation summarization failed: %s", exc)

        # Fallback: extract key content manually
        return self._fallback_summary(messages, max_words)

    @staticmethod
    def _fallback_summary(messages: list[dict[str, str]], max_words: int) -> str:
        """Fallback extractive summary when LLM is unavailable."""
        key_content: list[str] = []
        total_words = 0

        # Take first and last few user messages
        user_msgs = [m for m in messages if m.get("role") == "user"]
        important = user_msgs[:2] + user_msgs[-2:]

        for msg in important:
            content = msg.get("content", "")
            words = content.split()[:50]
            word_count = len(words)
            if total_words + word_count > max_words:
                break
            key_content.append(" ".join(words))
            total_words += word_count

        return " | ".join(key_content) if key_content else ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_summarizer: ConversationSummarizer | None = None


def get_summarizer() -> ConversationSummarizer:
    """Return the global conversation summarizer singleton."""
    global _summarizer
    if _summarizer is None:
        _summarizer = ConversationSummarizer()
    return _summarizer
