"""Base LLMClient implementation with connection setup."""

from __future__ import annotations

import httpx

from app.core.config import settings


class LLMClientBase:
    """Base client setup for Ollama connection management."""

    def __init__(self) -> None:
        self._host = settings.OLLAMA_HOST
        self._default_model = settings.OLLAMA_DEFAULT_MODEL
        self._embedding_model = settings.OLLAMA_EMBEDDING_MODEL
        self._keep_alive = settings.OLLAMA_KEEP_ALIVE
        self._temperature = settings.OLLAMA_TEMPERATURE
        self._top_p = settings.OLLAMA_TOP_P
        self._num_predict = settings.OLLAMA_NUM_PREDICT
        self._timeout = settings.OLLAMA_TIMEOUT_SECONDS

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._host,
            timeout=httpx.Timeout(
                self._timeout,
                connect=5.0,
                read=float(self._timeout),
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=settings.OLLAMA_MAX_CONNECTIONS,
                keepalive_expiry=30.0,
            ),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
