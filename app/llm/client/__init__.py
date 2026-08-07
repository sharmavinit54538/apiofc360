"""Unified LLMClient — backward-compatible interface that delegates to the multi-provider router.

All existing services import `get_llm_client()` which returns an `LLMClient` instance.
This updated version routes through the provider registry instead of directly calling Ollama.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from app.llm.router import LLMRouter, get_llm_router
from app.llm.providers.base import LLMResponse, EmbeddingResponse
from app.llm.cost_tracker import get_cost_tracker

logger = logging.getLogger(__name__)


class LLMClient:
    """Production-grade multi-provider LLM client.

    Maintains backward compatibility with the old Ollama-only interface while
    delegating to the multi-provider router for actual inference.
    """

    def __init__(self) -> None:
        self._router = get_llm_router()
        self._cost_tracker = get_cost_tracker()

    # ------------------------------------------------------------------
    # Chat (backward-compatible with old LLMChatMixin)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        num_predict: int | None = None,
        json_mode: bool = False,
        provider: str | None = None,
    ) -> str:
        """Generate a chat completion — returns content string for backward compatibility."""
        response = await self._router.chat(
            messages,
            model=model,
            provider=provider,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=num_predict or 2048,
            json_mode=json_mode,
        )

        # Track usage
        if response.total_tokens > 0:
            self._cost_tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
                endpoint="chat",
            )

        return response.content

    async def chat_full(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 2048,
        json_mode: bool = False,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Generate a chat completion — returns full LLMResponse with metadata."""
        response = await self._router.chat(
            messages,
            model=model,
            provider=provider,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
        )

        if response.total_tokens > 0:
            self._cost_tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
                endpoint="chat",
            )

        return response

    # ------------------------------------------------------------------
    # Streaming Chat (backward-compatible with old LLMChatMixin)
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield chat tokens as they arrive from the best available provider."""
        async for token in self._router.stream_chat(
            messages,
            model=model,
            provider=provider,
            temperature=temperature if temperature is not None else 0.3,
        ):
            yield token

    # ------------------------------------------------------------------
    # Completion (backward-compatible with old LLMCompletionsMixin)
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        num_predict: int | None = None,
        json_mode: bool = False,
        context: list[int] | None = None,
        provider: str | None = None,
    ) -> str:
        """Generate a completion by converting to chat format."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self.chat(
            messages,
            model=model,
            temperature=temperature,
            num_predict=num_predict or 2048,
            json_mode=json_mode,
            provider=provider,
        )

    async def stream_complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield completion tokens as they arrive."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async for token in self.stream_chat(
            messages,
            model=model,
            temperature=temperature,
            provider=provider,
        ):
            yield token

    # ------------------------------------------------------------------
    # Embeddings (backward-compatible with old LLMEmbeddingsMixin)
    # ------------------------------------------------------------------

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> list[float]:
        """Generate a vector embedding for the given text."""
        response = await self._router.embed([text], model=model, provider=provider)

        if response.total_tokens > 0:
            self._cost_tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.total_tokens,
                completion_tokens=0,
                endpoint="embed",
            )

        if response.embeddings and response.embeddings[0]:
            return response.embeddings[0]
        return []

    async def embed_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        response = await self._router.embed(texts, model=model, provider=provider)

        if response.total_tokens > 0:
            self._cost_tracker.record(
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.total_tokens,
                completion_tokens=0,
                endpoint="embed_batch",
            )

        return response.embeddings if response.embeddings else [[] for _ in texts]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def check_health(self) -> dict[str, Any]:
        """Check health of all providers."""
        return await self._router.health_check()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying provider connections."""
        await self._router.close()


# ---------------------------------------------------------------------------
# Singleton factory (backward-compatible)
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """FastAPI DI factory — returns the global LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
