"""Abstract base class for all LLM providers.

Every provider (OpenAI, Anthropic, Google, Ollama, OpenRouter, etc.) implements
this interface so the router can treat them uniformly.
"""

from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


class ProviderCapability(str, Enum):
    """Capabilities a provider may support."""
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    VISION = "vision"
    TOOL_CALLING = "tool_calling"
    JSON_MODE = "json_mode"
    STREAMING = "streaming"


@dataclass
class LLMResponse:
    """Standardised response from any LLM provider."""
    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: float = 0.0


@dataclass
class EmbeddingResponse:
    """Standardised embedding response."""
    embeddings: list[list[float]]
    model: str
    provider: str
    total_tokens: int = 0
    dimensions: int = 0
    cost_usd: float = 0.0


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    embedding_model: str = ""
    max_retries: int = 3
    timeout_seconds: int = 120
    rate_limit_rpm: int = 60
    enabled: bool = True
    priority: int = 100          # Lower = higher priority
    capabilities: set[ProviderCapability] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)


# Health recovery constants
HEALTH_COOLDOWN_SECONDS = 30  # Cooldown before retrying unhealthy provider


class LLMProviderBase(abc.ABC):
    """Abstract base for all LLM provider implementations."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.name = config.name
        self._healthy = True
        self._unhealthy_since: float | None = None  # Timestamp when marked unhealthy

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True when the provider is reachable and operational."""

    @property
    def is_healthy(self) -> bool:
        """Check if provider is healthy, with automatic half-open recovery after cooldown."""
        if self._healthy:
            return True
        # Half-open: allow recovery attempt after cooldown
        if self._unhealthy_since is not None:
            elapsed = time.time() - self._unhealthy_since
            if elapsed >= HEALTH_COOLDOWN_SECONDS:
                logger.info("Provider '%s' entering half-open state after %.0fs cooldown", self.name, elapsed)
                return True  # Allow one attempt to recover
        return False

    def mark_unhealthy(self) -> None:
        if self._healthy:
            self._healthy = False
            self._unhealthy_since = time.time()
            logger.warning("Provider '%s' marked unhealthy", self.name)

    def mark_healthy(self) -> None:
        if not self._healthy:
            self._healthy = True
            self._unhealthy_since = None
            logger.info("Provider '%s' recovered and marked healthy", self.name)

    # ------------------------------------------------------------------
    # Chat / Completion
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send a multi-turn chat request and return the assistant response."""

    @abc.abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Yield tokens as they arrive from the provider."""

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResponse:
        """Generate embeddings for one or more texts."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release any held resources (HTTP clients, etc.)."""

    # ------------------------------------------------------------------
    # Capability helpers
    # ------------------------------------------------------------------

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.config.capabilities

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} healthy={self._healthy}>"
