"""Token counting utilities for LLM requests.

Uses tiktoken for OpenAI models and approximate counting for others.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Approximate tokens-per-character ratios by provider
_CHARS_PER_TOKEN = {
    "openai": 4.0,
    "anthropic": 3.5,
    "google": 4.0,
    "ollama": 4.0,
    "openrouter": 4.0,
    "default": 4.0,
}

# Try to import tiktoken for accurate OpenAI counting
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


def count_tokens(text: str, model: str = "gpt-4o", provider: str = "openai") -> int:
    """Count tokens in a text string.

    Uses tiktoken for OpenAI models, approximate counting for others.
    """
    if not text:
        return 0

    # Try tiktoken for OpenAI models
    if provider == "openai" and _tiktoken is not None:
        enc = _get_tiktoken_encoding(model)
        if enc:
            return len(enc.encode(text))

    # Approximate counting
    ratio = _CHARS_PER_TOKEN.get(provider, _CHARS_PER_TOKEN["default"])
    return max(1, int(len(text) / ratio))


def count_messages_tokens(
    messages: list[dict[str, str]],
    model: str = "gpt-4o",
    provider: str = "openai",
) -> int:
    """Count total tokens across a list of chat messages.

    Includes per-message overhead for OpenAI models.
    """
    total = 0

    # OpenAI chat models have per-message overhead
    per_message_overhead = 4 if provider == "openai" else 2
    reply_overhead = 3 if provider == "openai" else 1

    for msg in messages:
        total += per_message_overhead
        for key, value in msg.items():
            if isinstance(value, str):
                total += count_tokens(value, model, provider)
            if key == "name":
                total -= 1  # role is omitted when name is present in OpenAI

    total += reply_overhead
    return total


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    provider: str = "openai",
) -> float:
    """Estimate cost in USD based on token counts.

    Prices are approximate and updated periodically.
    """
    # Pricing per 1M tokens: (input, output)
    pricing: dict[str, tuple[float, float]] = {
        # OpenAI
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.00, 30.00),
        "o1": (15.00, 60.00),
        "o1-mini": (3.00, 12.00),
        # Anthropic
        "claude-sonnet-4-20250514": (3.00, 15.00),
        "claude-3-5-sonnet-20241022": (3.00, 15.00),
        "claude-3-haiku-20240307": (0.25, 1.25),
        # Google
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-2.5-pro": (1.25, 10.00),
        "gemini-1.5-flash": (0.075, 0.30),
        # DeepSeek (via OpenRouter)
        "deepseek/deepseek-chat": (0.14, 0.28),
        "deepseek/deepseek-reasoner": (0.55, 2.19),
        # Embeddings
        "text-embedding-3-small": (0.02, 0.0),
        "text-embedding-3-large": (0.13, 0.0),
        "text-embedding-004": (0.0, 0.0),  # Free from Google
    }

    prices = pricing.get(model, (0.50, 1.50))  # Default conservative estimate
    input_cost = (prompt_tokens / 1_000_000) * prices[0]
    output_cost = (completion_tokens / 1_000_000) * prices[1]
    return round(input_cost + output_cost, 6)


# Ollama / self-hosted models are free
def is_free_provider(provider: str) -> bool:
    """Check if a provider is free (self-hosted)."""
    return provider in {"ollama"}
