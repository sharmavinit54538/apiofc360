"""Backward-compatible Ollama client wrapper.

This module preserves the `ollama_client` singleton and `OllamaClient` class
that all services import. All calls route directly through the production Ollama provider.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from app.llm.client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)


class OllamaClient:
    """Backward-compatible wrapper — delegates to the unified LLMClient / OllamaProvider.

    Services that import `from app.services.ollama_client import ollama_client`
    will continue to work seamlessly.
    """

    def __init__(self) -> None:
        self._llm: LLMClient | None = None

    @property
    def _client(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_llm_client()
        return self._llm

    async def check_health(self) -> bool:
        """Verify if Ollama AI server is running."""
        try:
            result = await self._client.check_health()
            return result.get("healthy", False)
        except Exception:
            return False

    async def get_embedding(self, text: str, model: str | None = None) -> list[float]:
        """Fetch vector embeddings using local Ollama."""
        return await self._client.embed(text, model=model)

    async def generate_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        json_format: bool = False,
        options: dict | None = None,
    ) -> str:
        """Call Ollama completion API."""
        temperature = 0.3
        num_predict = 2048
        if options:
            temperature = options.get("temperature", temperature)
            num_predict = options.get("num_predict", num_predict)

        return await self._client.complete(
            prompt=prompt,
            system=system_prompt,
            model=model,
            temperature=temperature,
            num_predict=num_predict,
            json_mode=json_format,
        )

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        json_format: bool = False,
        options: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream completion — yields dicts with 'response' key for compatibility."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        temperature = 0.3
        if options:
            temperature = options.get("temperature", temperature)

        async for token in self._client.stream_chat(
            messages, model=model, temperature=temperature
        ):
            yield {"response": token, "done": False}

        yield {"response": "", "done": True}


# Global singleton client
ollama_client = OllamaClient()
