"""Ollama chat endpoint implementations (streaming and non-streaming)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from app.llm.client.base import LLMClientBase
from app.llm.client.constants import _MAX_RETRIES, _RETRY_BACKOFF_BASE

logger = logging.getLogger(__name__)


class LLMChatMixin(LLMClientBase):
    """Methods for multi-turn conversations using Ollama's /api/chat endpoints."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        num_predict: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """Generate a chat completion using Ollama /api/chat endpoint."""
        chosen_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature if temperature is not None else self._temperature,
                "top_p": self._top_p,
                "num_predict": num_predict if num_predict is not None else self._num_predict,
            },
        }
        if json_mode:
            payload["format"] = "json"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                res = await self._client.post("/api/chat", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("message", {}).get("content", "").strip()
                logger.warning(
                    "Ollama chat HTTP %s (attempt %d/%d)", res.status_code, attempt, _MAX_RETRIES
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Ollama chat connection error (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF_BASE ** attempt)

        logger.error("All %d Ollama chat retries exhausted.", _MAX_RETRIES)
        return ""

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield chat tokens as they arrive from Ollama (streaming)."""
        chosen_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature if temperature is not None else self._temperature,
                "top_p": self._top_p,
            },
        }

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    return
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:
            logger.error("Ollama chat stream failed: %s", exc)
