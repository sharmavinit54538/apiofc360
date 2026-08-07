"""Context manager — controls token budgets, trims history, triggers summarization.

Ensures conversations never exceed the model's context window while preserving
the most important context.
"""

from __future__ import annotations

import logging
from typing import Any

from app.llm.token_counter import count_tokens, count_messages_tokens

logger = logging.getLogger(__name__)

# Default context windows per provider/model family
_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    # Anthropic
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Google
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    # Ollama / local
    "llama3": 8_192,
    "llama3.1": 128_000,
    "llama3.2": 128_000,
    "qwen2.5": 32_768,
    "qwen2.5:7b": 32_768,
    "mistral": 32_768,
    "deepseek-r1": 64_000,
    "gemma": 8_192,
    "gemma:2b": 8_192,
    "gemma2": 8_192,
    "phi4": 16_384,
    # Default
    "default": 8_192,
}


def get_context_window(model: str) -> int:
    """Get the context window size for a model."""
    # Try exact match first
    if model in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[model]
    # Try prefix match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    for prefix, window in _CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return _CONTEXT_WINDOWS["default"]


class ContextManager:
    """Manages context window budgets for LLM conversations.

    Responsibilities:
    - Estimate token usage for message lists
    - Trim older messages when context window is exceeded
    - Reserve tokens for system prompt and response
    - Trigger summarization of older context when trimming
    """

    def __init__(
        self,
        model: str = "llama3",
        provider: str = "ollama",
        max_response_tokens: int = 2048,
        system_reserve_tokens: int = 500,
    ) -> None:
        self.model = model
        self.provider = provider
        self.context_window = get_context_window(model)
        self.max_response_tokens = max_response_tokens
        self.system_reserve = system_reserve_tokens
        self.available_for_context = self.context_window - max_response_tokens - system_reserve_tokens

    def trim_messages(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        """Trim messages to fit within the context window.

        Strategy:
        1. Always keep the system message(s)
        2. Always keep the last user message
        3. Keep as many recent messages as possible within budget
        """
        budget = max_tokens or self.available_for_context

        # Separate system messages from conversation
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]

        if not conv_msgs:
            return messages

        # Calculate system token usage
        system_tokens = sum(count_tokens(m["content"], self.model, self.provider) for m in system_msgs)
        remaining_budget = budget - system_tokens

        if remaining_budget <= 0:
            # System prompt alone exceeds budget — keep system + last message only
            return system_msgs[-1:] + conv_msgs[-1:]

        # Build from most recent backward
        trimmed: list[dict[str, str]] = []
        tokens_used = 0

        for msg in reversed(conv_msgs):
            msg_tokens = count_tokens(msg["content"], self.model, self.provider)
            if tokens_used + msg_tokens > remaining_budget:
                break
            trimmed.append(msg)
            tokens_used += msg_tokens

        trimmed.reverse()

        # If no messages fit, keep at least the last one
        if not trimmed and conv_msgs:
            trimmed = conv_msgs[-1:]

        return system_msgs + trimmed

    def estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """Estimate total tokens for a message list."""
        return count_messages_tokens(messages, self.model, self.provider)

    def needs_trimming(self, messages: list[dict[str, str]]) -> bool:
        """Check if messages exceed the available context budget."""
        return self.estimate_tokens(messages) > self.available_for_context

    def get_budget_info(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Get detailed token budget information."""
        current_tokens = self.estimate_tokens(messages)
        return {
            "model": self.model,
            "context_window": self.context_window,
            "max_response_tokens": self.max_response_tokens,
            "system_reserve": self.system_reserve,
            "available_for_context": self.available_for_context,
            "current_tokens": current_tokens,
            "remaining_tokens": max(0, self.available_for_context - current_tokens),
            "needs_trimming": current_tokens > self.available_for_context,
            "message_count": len(messages),
        }
