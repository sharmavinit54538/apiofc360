"""Token counting utilities for LLM requests.

Uses tiktoken for OpenAI-compatible models and approximate counting for others.
Ollama (self-hosted) is the exclusive provider.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Approximate tokens-per-character ratios
_CHARS_PER_TOKEN = {
    "ollama": 4.0,
    "default": 4.0,
}

# Try to import tiktoken for accurate counting
_tiktoken = None
try:
    import tiktoken as _tiktoken_module
    _tiktoken = _tiktoken_module
except ImportError:
    logger.info("tiktoken not installed — using approximate token counting")


@lru_cache(maxsize=8)
def _get_tiktoken_encoding(model: str):
    """Get tiktoken encoding for a model name, with caching."""
    if _tiktoken is None:
        return None
    try:
        return _tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return _tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None


def count_tokens(text: str, model: str = "qwen3:30b", provider: str = "ollama") -> int:
    """Count tokens in a text string.

    Uses tiktoken if available, approximate counting for Ollama/other providers.
    """
    if not text:
        return 0

    # Try tiktoken for models that support it
    if _tiktoken is not None:
        enc = _get_tiktoken_encoding(model)
        if enc:
            return len(enc.encode(text))

    # Approximate counting
    ratio = _CHARS_PER_TOKEN.get(provider, _CHARS_PER_TOKEN["default"])
    return max(1, int(len(text) / ratio))


def count_messages_tokens(
    messages: list[dict[str, str]],
    model: str = "qwen3:30b",
    provider: str = "ollama",
) -> int:
    """Count total tokens across a list of chat messages."""
    total = 0

    # Standard per-message overhead
    per_message_overhead = 2
    reply_overhead = 1

    for msg in messages:
        total += per_message_overhead
        for key, value in msg.items():
            if isinstance(value, str):
                total += count_tokens(value, model, provider)
            if key == "name":
                total -= 1

    total += reply_overhead
    return total


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    provider: str = "ollama",
) -> float:
    """Estimate cost in USD based on token counts.

    Ollama is free (self-hosted).
    """
    # Ollama and self-hosted models are free
    if provider == "ollama":
        return 0.0
    
    # Fallback for any other provider (should not happen in Ollama-only setup)
    return 0.0


# Ollama / self-hosted models are free
def is_free_provider(provider: str) -> bool:
    """Check if a provider is free (self-hosted)."""
    return provider == "ollama"
