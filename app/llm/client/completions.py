"""Ollama generation/completion endpoints (streaming and non-streaming)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from app.llm.client.base import LLMClientBase
from app.llm.client.constants import _MAX_RETRIES, _RETRY_BACKOFF_BASE

logger = logging.getLogger(__name__)


class LLMCompletionsMixin(LLMClientBase):
    """Methods for prompting Ollama's /api/generate endpoints."""

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
    ) -> str:
        """Generate a completion (non-streaming)."""
        chosen_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": chosen_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature if temperature is not None else self._temperature,
                "top_p": self._top_p,
                "num_predict": num_predict if num_predict is not None else self._num_predict,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        if context:
            payload["context"] = context

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                res = await self._client.post("/api/generate", json=payload)
                if res.status_code == 200:
                    return res.json().get("response", "").strip()
                logger.warning(
                    "Ollama generate HTTP %s (attempt %d/%d): %s",
                    res.status_code, attempt, _MAX_RETRIES, res.text[:200],
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Ollama connection error (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF_BASE ** attempt)

        logger.error("All %d Ollama retries exhausted for model '%s'.", _MAX_RETRIES, chosen_model)
        return ""

    async def stream_complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield text tokens as they arrive from Ollama (streaming)."""
        chosen_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": chosen_model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature if temperature is not None else self._temperature,
                "top_p": self._top_p,
            },
        }
        if system:
            payload["system"] = system

        try:
            async with self._client.stream("POST", "/api/generate", json=payload) as response:
                if response.status_code != 200:
                    logger.error("Ollama stream returned HTTP %s", response.status_code)
                    return
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:
            logger.error("Ollama stream failed: %s", exc)
