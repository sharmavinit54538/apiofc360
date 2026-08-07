"""Google Gemini provider — supports Gemini 2.0 Flash, Gemini 2.5 Pro, etc."""

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


class GoogleProvider(LLMProviderBase):
    """Production Google Gemini provider using direct Generative Language API."""

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
        self._api_key = config.api_key
        base = config.base_url or "https://generativelanguage.googleapis.com"
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[dict[str, str]]) -> tuple[str, list[dict]]:
        """Convert OpenAI-style messages to Gemini format.

        Returns (system_instruction, contents).
        """
        system_text = ""
        contents: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_text += content + "\n"
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        return system_text.strip(), contents

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            res = await self._client.get(
                f"/v1beta/models?key={self._api_key}",
                timeout=10.0,
            )
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("Google health check failed: %s", exc)
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
        chosen_model = model or self.config.default_model or "gemini-2.0-flash"
        t0 = time.perf_counter()

        system_text, contents = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        url = f"/v1beta/models/{chosen_model}:generateContent?key={self._api_key}"

        for attempt in range(1, self.config.max_retries + 1):
            try:
                res = await self._client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    content = ""
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        content = "".join(p.get("text", "") for p in parts)

                    usage = data.get("usageMetadata", {})
                    latency = (time.perf_counter() - t0) * 1000

                    self.mark_healthy()
                    return LLMResponse(
                        content=content,
                        model=chosen_model,
                        provider="google",
                        prompt_tokens=usage.get("promptTokenCount", 0),
                        completion_tokens=usage.get("candidatesTokenCount", 0),
                        total_tokens=usage.get("totalTokenCount", 0),
                        finish_reason=candidates[0].get("finishReason", "STOP") if candidates else "STOP",
                        raw=data,
                        latency_ms=latency,
                    )

                if res.status_code == 429:
                    logger.warning("Google rate limited (attempt %d)", attempt)
                    await asyncio.sleep(_RETRY_BACKOFF ** attempt)
                    continue

                if res.status_code >= 500:
                    logger.warning("Google server error %s (attempt %d)", res.status_code, attempt)
                else:
                    logger.error("Google error %s: %s", res.status_code, res.text[:500])
                    break

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("Google connection error (attempt %d): %s", attempt, exc)

            if attempt < self.config.max_retries:
                await asyncio.sleep(_RETRY_BACKOFF ** attempt)

        self.mark_unhealthy()
        return LLMResponse(content="", model=chosen_model, provider="google")

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
        chosen_model = model or self.config.default_model or "gemini-2.0-flash"
        system_text, contents = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = f"/v1beta/models/{chosen_model}:streamGenerateContent?key={self._api_key}&alt=sse"

        try:
            async with self._client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    logger.error("Google stream error: HTTP %s", response.status_code)
                    return
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        chunk = json.loads(data_str)
                        candidates = chunk.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                token = part.get("text", "")
                                if token:
                                    yield token
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.error("Google stream failed: %s", exc)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResponse:
        chosen_model = model or self.config.embedding_model or "text-embedding-004"

        # Gemini embedding API supports batch
        requests_list = [
            {"model": f"models/{chosen_model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
        payload = {"requests": requests_list}
        url = f"/v1beta/models/{chosen_model}:batchEmbedContents?key={self._api_key}"

        for attempt in range(1, self.config.max_retries + 1):
            try:
                res = await self._client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    embeddings_data = data.get("embeddings", [])
                    embeddings = [e.get("values", []) for e in embeddings_data]
                    dims = len(embeddings[0]) if embeddings and embeddings[0] else 0
                    return EmbeddingResponse(
                        embeddings=embeddings,
                        model=chosen_model,
                        provider="google",
                        dimensions=dims,
                    )
                logger.warning("Google embed HTTP %s (attempt %d)", res.status_code, attempt)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("Google embed error (attempt %d): %s", attempt, exc)

            if attempt < self.config.max_retries:
                await asyncio.sleep(_RETRY_BACKOFF ** attempt)

        return EmbeddingResponse(embeddings=[], model=chosen_model, provider="google")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
