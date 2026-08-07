"""Production-ready Ollama provider.

Supports local LLMs (Llama 3.1, Qwen, Mistral, DeepSeek, Gemma, Phi, etc.) with:
- Connection pooling via reusable httpx.AsyncClient
- Health check via GET /api/tags before generation requests
- Model validation & auto-pull (POST /api/pull)
- 3-attempt exponential backoff retry logic (1s, 2s, 4s)
- 60-second default request timeout
- Differentiated error handling & HTTP exceptions
- Detailed metrics logging (prompt tokens, completion tokens, latency, retries)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.llm.providers.base import (
    EmbeddingResponse,
    LLMProviderBase,
    LLMResponse,
    ProviderCapability,
    ProviderConfig,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProviderBase):
    """Production-ready self-hosted Ollama provider."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                ProviderCapability.CHAT,
                ProviderCapability.COMPLETION,
                ProviderCapability.EMBEDDING,
                ProviderCapability.JSON_MODE,
                ProviderCapability.STREAMING,
            }
        super().__init__(config)

        base_url = (
            config.base_url
            or getattr(settings, "OLLAMA_BASE_URL", None)
            or getattr(settings, "OLLAMA_HOST", "http://127.0.0.1:11434")
        )
        base_url = base_url.rstrip("/")

        timeout_sec = (
            config.timeout_seconds
            or getattr(settings, "OLLAMA_TIMEOUT", None)
            or getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 60)
        )
        self.timeout_sec = float(timeout_sec)

        # Persistent connection pool (httpx.AsyncClient singleton)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(self.timeout_sec, connect=5.0, read=self.timeout_sec),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=config.extra.get("max_connections", 50),
            ),
        )
        self._keep_alive = config.extra.get("keep_alive", "30m")
        self._top_p = config.extra.get("top_p", 0.9)
        self._num_predict = config.extra.get("num_predict", 2048)

    # ------------------------------------------------------------------
    # Health Check & Model Validation
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Ping Ollama GET /api/tags to check health."""
        try:
            res = await self._client.get("/api/tags", timeout=5.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception:
            self._healthy = False
            return False

    async def _verify_health_or_raise(self) -> list[str]:
        """Perform health check before generation.

        Returns list of installed model names if healthy, else raises HTTPException 503.
        """
        try:
            res = await self._client.get("/api/tags", timeout=5.0)
            if res.status_code != 200:
                self.mark_unhealthy()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Ollama server is not running.",
                )
            self.mark_healthy()
            data = res.json()
            models_list = data.get("models", [])
            installed_models = []
            for m in models_list:
                name = m.get("name") or m.get("model")
                if name:
                    installed_models.append(name)
            return installed_models
        except HTTPException:
            raise
        except (httpx.ConnectError, httpx.NetworkError):
            self.mark_unhealthy()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )
        except httpx.TimeoutException:
            self.mark_unhealthy()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Ollama health check timed out after 5.0 seconds.",
            )
        except Exception as exc:
            self.mark_unhealthy()
            logger.error("Ollama health check exception: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )

    async def validate_or_pull_model(self, requested_model: str) -> str:
        """Ensure requested model exists. If not, auto-pull via POST /api/pull or match available installed model."""
        installed = await self._verify_health_or_raise()
        if not installed:
            return requested_model

        clean_req = requested_model.strip().lower()
        req_base = clean_req.split(":")[0]

        # 1. Exact match
        for m in installed:
            if m.lower() == clean_req:
                return m

        # 2. Base name match (e.g. "llama3" matches "llama3:latest")
        for m in installed:
            m_base = m.lower().split(":")[0]
            if m_base == req_base:
                return m

        # 3. Fuzzy / Prefix match (e.g. "llama3.1" matches "llama3:latest")
        for m in installed:
            m_base = m.lower().split(":")[0]
            if req_base.startswith(m_base) or m_base.startswith(req_base):
                return m

        # 4. Attempt auto-pull
        logger.info("Model '%s' not found in local Ollama tags. Attempting auto-pull...", requested_model)
        try:
            pull_res = await self._client.post(
                "/api/pull",
                json={"name": requested_model, "stream": False},
                timeout=httpx.Timeout(180.0, connect=10.0, read=180.0),
            )
            if pull_res.status_code == 200:
                logger.info("Successfully pulled model '%s'", requested_model)
                return requested_model
        except Exception as pull_exc:
            logger.warning("Auto-pull for model '%s' failed: %s", requested_model, pull_exc)

        # 5. Fallback to first non-embedding installed model if pull unavailable
        for m in installed:
            if "embed" not in m.lower():
                logger.info("Using installed fallback model '%s' for request '%s'", m, requested_model)
                return m

        return installed[0]


    # ------------------------------------------------------------------
    # Chat Generation
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
        chosen_model = model or self.config.default_model or "llama3.1"
        verified_model = await self.validate_or_pull_model(chosen_model)

        t0 = time.perf_counter()
        payload: dict[str, Any] = {
            "model": verified_model,
            "messages": messages,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature,
                "top_p": self._top_p,
                "num_predict": max_tokens or self._num_predict,
            },
        }
        if json_mode:
            payload["format"] = "json"

        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                res = await self._client.post("/api/chat", json=payload)

                if res.status_code == 200:
                    try:
                        data = res.json()
                    except Exception:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Invalid response from Ollama server.",
                        )

                    content = data.get("message", {}).get("content", "").strip()
                    latency_ms = (time.perf_counter() - t0) * 1000
                    prompt_tokens = data.get("prompt_eval_count", 0)
                    completion_tokens = data.get("eval_count", 0)

                    logger.info(
                        "Ollama chat request | model=%s | prompt_tokens=%d | completion_tokens=%d | latency=%.2fms | retries=%d",
                        verified_model,
                        prompt_tokens,
                        completion_tokens,
                        latency_ms,
                        attempt - 1,
                    )
                    self.mark_healthy()

                    return LLMResponse(
                        content=content,
                        model=data.get("model", verified_model),
                        provider="ollama",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                        finish_reason=data.get("done_reason", "stop"),
                        raw=data,
                        latency_ms=latency_ms,
                    )

                if res.status_code in (404, 400):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Model {verified_model} not installed.",
                    )

                if res.status_code >= 500:
                    logger.warning("Ollama server error %d (attempt %d/%d)", res.status_code, attempt, max_retries)

            except HTTPException:
                raise
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_exc = exc
                logger.warning(
                    "Ollama connection error (attempt %d/%d): %s", attempt, max_retries, exc
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Ollama request timeout (attempt %d/%d): %s", attempt, max_retries, exc
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Ollama chat unexpected error (attempt %d/%d): %s", attempt, max_retries, exc
                )

            if attempt < max_retries:
                backoff_sec = 2 ** (attempt - 1)  # 1s, 2s, 4s
                await asyncio.sleep(backoff_sec)

        self.mark_unhealthy()
        if isinstance(last_exc, httpx.TimeoutException):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Ollama request timed out after {int(self.timeout_sec)} seconds.",
            )
        elif isinstance(last_exc, (httpx.ConnectError, httpx.NetworkError)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server unavailable.",
        )

    # ------------------------------------------------------------------
    # Legacy / Direct Generate Completion
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Call Ollama /api/generate directly."""
        chosen_model = model or self.config.default_model or "llama3.1"
        verified_model = await self.validate_or_pull_model(chosen_model)

        t0 = time.perf_counter()
        payload: dict[str, Any] = {
            "model": verified_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature,
                "top_p": self._top_p,
                "num_predict": max_tokens or self._num_predict,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                res = await self._client.post("/api/generate", json=payload)
                if res.status_code == 200:
                    try:
                        data = res.json()
                    except Exception:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Invalid response from Ollama server.",
                        )

                    latency_ms = (time.perf_counter() - t0) * 1000
                    prompt_tokens = data.get("prompt_eval_count", 0)
                    completion_tokens = data.get("eval_count", 0)

                    logger.info(
                        "Ollama generate request | model=%s | prompt_tokens=%d | completion_tokens=%d | latency=%.2fms | retries=%d",
                        verified_model,
                        prompt_tokens,
                        completion_tokens,
                        latency_ms,
                        attempt - 1,
                    )
                    self.mark_healthy()

                    return LLMResponse(
                        content=data.get("response", "").strip(),
                        model=data.get("model", verified_model),
                        provider="ollama",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                        raw=data,
                        latency_ms=latency_ms,
                    )

                if res.status_code in (404, 400):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Model {verified_model} not installed.",
                    )

            except HTTPException:
                raise
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_exc = exc
                logger.warning(
                    "Ollama generate connection error (attempt %d/%d): %s", attempt, max_retries, exc
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Ollama generate timeout (attempt %d/%d): %s", attempt, max_retries, exc
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Ollama generate error (attempt %d/%d): %s", attempt, max_retries, exc
                )

            if attempt < max_retries:
                backoff_sec = 2 ** (attempt - 1)
                await asyncio.sleep(backoff_sec)

        self.mark_unhealthy()
        if isinstance(last_exc, httpx.TimeoutException):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Ollama request timed out after {int(self.timeout_sec)} seconds.",
            )
        elif isinstance(last_exc, (httpx.ConnectError, httpx.NetworkError)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server unavailable.",
        )

    # ------------------------------------------------------------------
    # Streaming Chat & Completions
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        chosen_model = model or self.config.default_model or "llama3.1"
        verified_model = await self.validate_or_pull_model(chosen_model)

        payload: dict[str, Any] = {
            "model": verified_model,
            "messages": messages,
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature,
                "top_p": self._top_p,
            },
        }

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Ollama server unavailable.",
                    )
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
        except HTTPException:
            raise
        except (httpx.ConnectError, httpx.NetworkError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Ollama stream timed out after {int(self.timeout_sec)} seconds.",
            )
        except Exception as exc:
            logger.error("Ollama stream_chat failed: %s", exc)

    async def stream_generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncGenerator[str, None]:
        """Stream raw text tokens from POST /api/generate."""
        chosen_model = model or self.config.default_model or "llama3.1"
        verified_model = await self.validate_or_pull_model(chosen_model)

        payload: dict[str, Any] = {
            "model": verified_model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": temperature,
                "top_p": self._top_p,
            },
        }
        if system:
            payload["system"] = system

        try:
            async with self._client.stream("POST", "/api/generate", json=payload) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Ollama server unavailable.",
                    )
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
        except HTTPException:
            raise
        except (httpx.ConnectError, httpx.NetworkError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama server is not running.",
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Ollama stream timed out after {int(self.timeout_sec)} seconds.",
            )
        except Exception as exc:
            logger.error("Ollama stream_generate failed: %s", exc)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResponse:
        chosen_model = model or self.config.embedding_model or "nomic-embed-text"
        embeddings: list[list[float]] = []

        for text in texts:
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    res = await self._client.post(
                        "/api/embeddings",
                        json={
                            "model": chosen_model,
                            "prompt": text,
                            "keep_alive": self._keep_alive,
                        },
                    )
                    if res.status_code == 200:
                        embedding = res.json().get("embedding", [])
                        if embedding:
                            embeddings.append(embedding)
                            break
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    logger.warning("Ollama embed error (attempt %d): %s", attempt, exc)

                if attempt < self.config.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))
            else:
                embeddings.append([])

        dims = len(embeddings[0]) if embeddings and embeddings[0] else 0
        return EmbeddingResponse(
            embeddings=embeddings,
            model=chosen_model,
            provider="ollama",
            dimensions=dims,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close reusable httpx client pool."""
        await self._client.aclose()
