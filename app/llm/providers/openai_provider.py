"""OpenAI GPT provider — supports GPT-4o, GPT-4o-mini, o1, text-embedding-3-*."""

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


class OpenAIProvider(LLMProviderBase):
    """Production OpenAI provider using direct HTTP (no SDK dependency)."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                ProviderCapability.CHAT,
                ProviderCapability.COMPLETION,
                ProviderCapability.EMBEDDING,
                ProviderCapability.VISION,
                ProviderCapability.TOOL_CALLING,
                ProviderCapability.JSON_MODE,
                ProviderCapability.STREAMING,
            }
        super().__init__(config)
        base = config.base_url or "https://api.openai.com/v1"
        self._client = httpx.AsyncClient(
            base_url=base,
            headers={
                "Authorization": f"Bearer {config.api_key}",
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
            res = await self._client.get("/models", timeout=10.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("OpenAI health check failed: %s", exc)
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
        chosen_model = model or self.config.default_model or "gpt-4o-mini"
        t0 = time.perf_counter()

        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools

        for attempt in range(1, self.config.max_retries + 1):
            try:
                res = await self._client.post("/chat/completions", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    choice = data["choices"][0]
                    usage = data.get("usage", {})
                    latency = (time.perf_counter() - t0) * 1000

                    self.mark_healthy()
                    return LLMResponse(
                        content=choice["message"]["content"] or "",
                        model=data.get("model", chosen_model),
                        provider="openai",
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        finish_reason=choice.get("finish_reason", "stop"),
                        raw=data,
                        latency_ms=latency,
                    )

                if res.status_code == 429:
                    retry_after = float(res.headers.get("retry-after", _RETRY_BACKOFF ** attempt))
                    logger.warning("OpenAI rate limited, retrying in %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if res.status_code >= 500:
                    logger.warning("OpenAI server error %s (attempt %d/%d)", res.status_code, attempt, self.config.max_retries)
                else:
                    logger.error("OpenAI error %s: %s", res.status_code, res.text[:500])
                    break

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("OpenAI connection error (attempt %d/%d): %s", attempt, self.config.max_retries, exc)

            if attempt < self.config.max_retries:
                await asyncio.sleep(_RETRY_BACKOFF ** attempt)

        self.mark_unhealthy()
        return LLMResponse(content="", model=chosen_model, provider="openai")

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
        chosen_model = model or self.config.default_model or "gpt-4o-mini"
        payload = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    logger.error("OpenAI stream error: HTTP %s", response.status_code)
                    return
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.error("OpenAI stream failed: %s", exc)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResponse:
        chosen_model = model or self.config.embedding_model or "text-embedding-3-small"
        payload = {
            "model": chosen_model,
            "input": texts,
        }

        for attempt in range(1, self.config.max_retries + 1):
            try:
                res = await self._client.post("/embeddings", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    embeddings = [item["embedding"] for item in data["data"]]
                    usage = data.get("usage", {})
                    dims = len(embeddings[0]) if embeddings and embeddings[0] else 0
                    return EmbeddingResponse(
                        embeddings=embeddings,
                        model=data.get("model", chosen_model),
                        provider="openai",
                        total_tokens=usage.get("total_tokens", 0),
                        dimensions=dims,
                    )
                logger.warning("OpenAI embed HTTP %s (attempt %d)", res.status_code, attempt)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("OpenAI embed error (attempt %d): %s", attempt, exc)

            if attempt < self.config.max_retries:
                await asyncio.sleep(_RETRY_BACKOFF ** attempt)

        return EmbeddingResponse(embeddings=[], model=chosen_model, provider="openai")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
