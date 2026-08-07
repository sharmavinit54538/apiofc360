"""Anthropic Claude provider — supports Claude 3.5 Sonnet, Claude 4, etc."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

import httpx

from app.llm.providers.base import (
    EmbeddingResponse,
    LLMProviderBase,
    LLMResponse,
    ProviderCapability,
    ProviderConfig,
)

logger = logging.getLogger(__name__)

_RETRY_BACKOFF = 1.5
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProviderBase):
    """Production Anthropic Claude provider using direct HTTP."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                ProviderCapability.CHAT,
                ProviderCapability.VISION,
                ProviderCapability.TOOL_CALLING,
                ProviderCapability.JSON_MODE,
                ProviderCapability.STREAMING,
            }
        super().__init__(config)
        base = config.base_url or "https://api.anthropic.com"
        self._client = httpx.AsyncClient(
            base_url=base,
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            # Anthropic doesn't have a /models list — send a minimal chat
            res = await self._client.post(
                "/v1/messages",
                json={
                    "model": self.config.default_model or "claude-sonnet-4-20250514",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=15.0,
            )
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("Anthropic health check failed: %s", exc)
            self._healthy = False
            return False

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

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
        chosen_model = model or self.config.default_model or "claude-sonnet-4-20250514"
        t0 = time.perf_counter()

        # Anthropic requires system message to be separate
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text += msg.get("content", "") + "\n"
            else:
                user_messages.append(msg)

        if json_mode and system_text:
            system_text += "\nYou MUST respond with valid JSON only. No explanation, no markdown."

        if not user_messages:
            user_messages = [{"role": "user", "content": "Hello"}]

        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()
        if tools:
            payload["tools"] = tools

        for attempt in range(1, self.config.max_retries + 1):
            try:
                res = await self._client.post("/v1/messages", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content_blocks = data.get("content", [])
                    text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
                    content = "\n".join(text_parts)
                    usage = data.get("usage", {})
                    latency = (time.perf_counter() - t0) * 1000

                    self.mark_healthy()
                    return LLMResponse(
                        content=content,
                        model=data.get("model", chosen_model),
                        provider="anthropic",
                        prompt_tokens=usage.get("input_tokens", 0),
                        completion_tokens=usage.get("output_tokens", 0),
                        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                        finish_reason=data.get("stop_reason", "end_turn"),
                        raw=data,
                        latency_ms=latency,
                    )

                if res.status_code == 429:
                    retry_after = float(res.headers.get("retry-after", _RETRY_BACKOFF ** attempt))
                    logger.warning("Anthropic rate limited, retrying in %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if res.status_code >= 500:
                    logger.warning("Anthropic server error %s (attempt %d/%d)", res.status_code, attempt, self.config.max_retries)
                else:
                    logger.error("Anthropic error %s: %s", res.status_code, res.text[:500])
                    break

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("Anthropic connection error (attempt %d/%d): %s", attempt, self.config.max_retries, exc)

            if attempt < self.config.max_retries:
                await asyncio.sleep(_RETRY_BACKOFF ** attempt)

        self.mark_unhealthy()
        return LLMResponse(content="", model=chosen_model, provider="anthropic")

    # ------------------------------------------------------------------
    # Streaming Chat
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        chosen_model = model or self.config.default_model or "claude-sonnet-4-20250514"

        system_text = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text += msg.get("content", "") + "\n"
            else:
                user_messages.append(msg)

        if not user_messages:
            user_messages = [{"role": "user", "content": "Hello"}]

        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()

        try:
            async with self._client.stream("POST", "/v1/messages", json=payload) as response:
                if response.status_code != 200:
                    logger.error("Anthropic stream error: HTTP %s", response.status_code)
                    return
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        event = json.loads(data_str)
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            token = delta.get("text", "")
                            if token:
                                yield token
                        elif event.get("type") == "message_stop":
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.error("Anthropic stream failed: %s", exc)

    # ------------------------------------------------------------------
    # Embeddings (Anthropic does NOT offer embeddings — return empty)
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResponse:
        logger.warning("Anthropic does not provide embedding models. Use OpenAI or Ollama for embeddings.")
        return EmbeddingResponse(embeddings=[], model="none", provider="anthropic")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
