"""Intelligent LLM Router — selects the best provider, handles fallback, tracks usage.

This is the core orchestration layer that all services call through.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator

from app.llm.providers.base import (
    EmbeddingResponse,
    LLMProviderBase,
    LLMResponse,
    ProviderCapability,
)
from app.llm.providers.registry import get_provider_registry

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests to the best available provider with automatic fallback.

    Selection strategy:
    1. Use explicitly requested provider/model if specified
    2. Use the highest-priority healthy provider
    3. On failure, cascade through fallback chain
    4. Never expose internal errors to callers — return empty response as last resort
    """

    def __init__(self) -> None:
        self._registry = get_provider_registry()

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def _resolve_provider(
        self,
        provider_name: str | None = None,
        capability: ProviderCapability = ProviderCapability.CHAT,
    ) -> list[LLMProviderBase]:
        """Return an ordered list of providers to try.

        If provider_name is given, that provider is tried first.
        Remaining healthy providers follow in priority order.
        """
        candidates = self._registry.get_healthy(capability)

        if provider_name:
            requested = self._registry.get(provider_name)
            if requested and requested.is_healthy:
                # Put requested first, then others
                others = [p for p in candidates if p.name != provider_name]
                return [requested] + others
            elif requested:
                # Requested provider exists but unhealthy — still try it, then others
                return [requested] + candidates

        return candidates

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send a chat request with automatic provider fallback."""
        candidates = self._resolve_provider(provider, ProviderCapability.CHAT)

        if not candidates:
            logger.error("No LLM providers available for chat")
            return LLMResponse(content="", model=model or "unknown", provider="none")

        last_response = None
        for prov in candidates:
            try:
                logger.debug("Attempting chat with provider '%s' (model=%s)", prov.name, model or prov.config.default_model)
                response = await prov.chat(
                    messages,
                    model=model if provider else None,  # Only pass model if specific provider requested
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    tools=tools,
                )

                if response.content:
                    logger.info(
                        "Chat completed: provider=%s model=%s tokens=%d latency=%.0fms",
                        response.provider, response.model, response.total_tokens, response.latency_ms,
                    )
                    return response

                last_response = response
                logger.warning("Provider '%s' returned empty content, trying next", prov.name)

            except Exception as exc:
                logger.warning("Provider '%s' chat failed: %s", prov.name, exc)
                prov.mark_unhealthy()
                continue

        logger.error("All providers exhausted for chat request")
        return last_response or LLMResponse(content="", model=model or "unknown", provider="none")

    # ------------------------------------------------------------------
    # Streaming Chat
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Stream chat tokens with automatic provider fallback."""
        candidates = self._resolve_provider(provider, ProviderCapability.STREAMING)

        for prov in candidates:
            try:
                got_tokens = False
                async for token in prov.stream_chat(
                    messages,
                    model=model if provider else None,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    got_tokens = True
                    yield token

                if got_tokens:
                    return
                logger.warning("Provider '%s' stream returned no tokens, trying next", prov.name)

            except Exception as exc:
                logger.warning("Provider '%s' stream failed: %s", prov.name, exc)
                prov.mark_unhealthy()
                continue

        logger.error("All providers exhausted for stream request")

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> EmbeddingResponse:
        """Generate embeddings with automatic provider fallback."""
        candidates = self._resolve_provider(provider, ProviderCapability.EMBEDDING)

        for prov in candidates:
            try:
                response = await prov.embed(texts, model=model if provider else None)
                if response.embeddings and any(len(e) > 0 for e in response.embeddings):
                    return response
                logger.warning("Provider '%s' returned empty embeddings, trying next", prov.name)
            except Exception as exc:
                logger.warning("Provider '%s' embed failed: %s", prov.name, exc)
                prov.mark_unhealthy()
                continue

        logger.error("All providers exhausted for embedding request")
        return EmbeddingResponse(embeddings=[], model=model or "unknown", provider="none")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Run health checks on all providers."""
        results = await self._registry.health_check_all()
        healthy_count = sum(1 for v in results.values() if v)
        return {
            "healthy": healthy_count > 0,
            "providers": results,
            "healthy_count": healthy_count,
            "total_count": len(results),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close all provider connections."""
        await self._registry.close_all()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the global LLM router singleton."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
