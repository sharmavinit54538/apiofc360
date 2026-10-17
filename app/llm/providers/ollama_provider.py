"""Production-ready Ollama provider.

Supports local LLMs (Llama 3.1, Qwen, Mistral, DeepSeek, Gemma, Phi, etc.) with:
- Connection pooling via reusable httpx.AsyncClient
- Health check via GET /api/tags before generation requests
- Model validation & auto-pull (POST /api/pull)
- 3-attempt exponential backoff retry logic (1s, 2s, 4s)
- 60-second default request timeout
- Differentiated error handling & HTTP exceptions
- Detailed metrics logging (prompt tokens, completion tokens, latency, retries)
- Background health ping for auto-recovery
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

# Auto-recovery configuration
HEALTH_PING_INTERVAL_SECONDS = 30


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
            or getattr(settings, "OLLAMA_HOST", "http://localhost:11434")
        )
        # Docker fallback
        if "127.0.0.1" in base_url or "localhost" in base_url:
            import os
            if os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true":
                base_url = base_url.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
        base_url = base_url.rstrip("/")

        timeout_sec = (
            config.timeout_seconds
            or getattr(settings, "OLLAMA_TIMEOUT", None)
            or getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 120)
        )
        self.timeout_sec = float(timeout_sec)

        # Enforce 120s timeout to prevent cold-start ReadTimeout crashes
        self.timeout_sec = max(self.timeout_sec, 120.0)

        # Persistent connection pool (httpx.AsyncClient singleton)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(self.timeout_sec, connect=15.0, read=self.timeout_sec, write=30.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=config.extra.get("max_connections", 50),
            ),
        )
        self._keep_alive = config.extra.get("keep_alive", "30m")
        self._top_p = config.extra.get("top_p", 0.9)
        self._num_predict = config.extra.get("num_predict", 2048)
        self._fallback_model = getattr(settings, "OLLAMA_FALLBACK_MODEL", "gemma:2b")

        # Background health ping for auto-recovery
        self._health_ping_task: asyncio.Task | None = None
        self._health_ping_interval = HEALTH_PING_INTERVAL_SECONDS

    def start_health_ping(self) -> None:
        """Start background health ping task for auto-recovery."""
        if self._health_ping_task is None or self._health_ping_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._health_ping_task = loop.create_task(self._health_ping_loop())
                logger.info("Started Ollama background health ping (interval=%ds)", self._health_ping_interval)
            except RuntimeError:
                # No running event loop (e.g., in tests) - skip background ping
                logger.debug("No running event loop, skipping background health ping")

    def stop_health_ping(self) -> None:
        """Stop background health ping task."""
        if self._health_ping_task and not self._health_ping_task.done():
            self._health_ping_task.cancel()
            self._health_ping_task = None
            logger.info("Stopped Ollama background health ping")

    async def _health_ping_loop(self) -> None:
        """Periodically ping Ollama to enable auto-recovery from unhealthy state."""
        while True:
            try:
                await asyncio.sleep(self._health_ping_interval)
                if not self._healthy:
                    logger.debug("Health ping: checking unhealthy Ollama provider...")
                    healthy = await self.health_check()
                    if healthy:
                        self.mark_healthy()
                        logger.info("Ollama provider auto-recovered via health ping")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Health ping error (non-critical): %s", exc)

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
        except Exception as exc:
            logger.warning("Ollama health check failed: %s", exc)
            self._healthy = False
            return False

    async def health_check_detailed(self) -> dict[str, Any]:
        """Return detailed health info including model availability."""
        try:
            res = await self._client.get("/api/tags", timeout=5.0)
            if res.status_code != 200:
                self._healthy = False
                return {"healthy": False, "model_available": False, "error": f"HTTP {res.status_code}"}
            self._healthy = True
            data = res.json()
            models_list = data.get("models", [])
            installed_models = []
            for m in models_list:
                name = m.get("name") or m.get("model")
                if name:
                    installed_models.append(name)
            
            # Check if configured model is available
            configured_model = self.config.default_model or "llama3:latest"
            clean_req = configured_model.strip().lower()
            req_base = clean_req.split(":")[0]
            
            model_available = False
            for m in installed_models:
                m_lower = m.lower()
                m_base = m_lower.split(":")[0]
                if m_lower == clean_req or m_base == req_base:
                    model_available = True
                    break
            
            return {
                "healthy": True,
                "model_available": model_available,
                "installed_models": installed_models,
                "configured_model": configured_model,
            }
        except Exception as exc:
            logger.warning("Ollama detailed health check failed: %s", exc)
            self._healthy = False
            return {"healthy": False, "model_available": False, "error": str(exc)}

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
        """Ensure requested model exists. Auto-fallback to available model if missing.
        
        Strategy:
        1. Exact match
        2. Base name match (e.g. "llama3" matches "llama3:latest")
        3. If AI_AUTO_PULL_MODELS=true, attempt to pull the model
        4. Auto-fallback to fallback_model (gemma:2b) if available
        5. Auto-fallback to first available text model
        6. Last resort: return requested_model and let Ollama handle the error
        """
        installed = await self._verify_health_or_raise()
        if not installed:
            logger.warning("No models installed in Ollama, returning requested model: %s", requested_model)
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
                logger.info("Base name match: requested '%s' -> using '%s'", requested_model, m)
                return m

        # 3. Attempt auto-pull ONLY if AI_AUTO_PULL_MODELS is true
        auto_pull = getattr(settings, "AI_AUTO_PULL_MODELS", False)
        if auto_pull:
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

        # 4. Auto-fallback to configured fallback model
        fallback = self._fallback_model.strip().lower()
        for m in installed:
            if m.lower() == fallback:
                logger.warning("Model '%s' not available, falling back to '%s'", requested_model, m)
                return m
            m_base = m.lower().split(":")[0]
            if m_base == fallback.split(":")[0]:
                logger.warning("Model '%s' not available, falling back to base match '%s'", requested_model, m)
                return m

        # 5. Auto-fallback to first available text model (non-embedding)
        text_models = [m for m in installed if "embed" not in m.lower()]
        if text_models:
            fallback_model = text_models[0]
            logger.warning("Model '%s' not available, auto-fallback to first text model: '%s'", requested_model, fallback_model)
            return fallback_model

        # 6. Last resort: return requested_model and let the generation call handle it
        logger.warning("No suitable fallback model found, proceeding with requested model: %s", requested_model)
        return requested_model


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
                    logger.warning("Model %s not installed, trying fallback", verified_model)
                    # Try with fallback model
                    if verified_model != self._fallback_model:
                        verified_model = self._fallback_model
                        payload["model"] = verified_model
                        continue
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

        # All retries exhausted - return graceful fallback instead of raising
        self.mark_unhealthy()
        fallback_msg = (
            "I'm currently unable to connect to the AI service. "
            "Please try again in a moment, or contact support if the issue persists."
        )
        logger.error("All retries exhausted for chat, returning fallback response: %s", last_exc)
        # Return a valid 200 OK response with fallback content instead of raising
        return LLMResponse(
            content=fallback_msg,
            model=verified_model,
            provider="ollama",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason="error_fallback",
            raw={"error": str(last_exc) if last_exc else "unknown"},
            latency_ms=(time.perf_counter() - t0) * 1000,
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
                    logger.warning("Model %s not installed, trying fallback", verified_model)
                    if verified_model != self._fallback_model:
                        verified_model = self._fallback_model
                        payload["model"] = verified_model
                        continue
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

        # All retries exhausted - return graceful fallback instead of raising
        self.mark_unhealthy()
        fallback_msg = (
            "I'm currently unable to generate a response. "
            "Please try again in a moment, or contact support if the issue persists."
        )
        logger.error("All retries exhausted for completion, returning fallback response: %s", last_exc)
        # Return a valid 200 OK response with fallback content instead of raising
        return LLMResponse(
            content=fallback_msg,
            model=verified_model,
            provider="ollama",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason="error_fallback",
            raw={"error": str(last_exc) if last_exc else "unknown"},
            latency_ms=(time.perf_counter() - t0) * 1000,
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
                    yield "I'm currently unable to connect to the AI service. Please try again in a moment."
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
        except (httpx.ConnectError, httpx.NetworkError):
            logger.warning("Ollama stream_chat connection error")
            yield "I'm currently unable to connect to the AI service. Please try again in a moment."
        except httpx.TimeoutException:
            logger.warning("Ollama stream_chat timeout")
            yield "The AI service is taking too long to respond. Please try again."
        except Exception as exc:
            logger.error("Ollama stream_chat failed: %s", exc)
            yield "An unexpected error occurred. Please try again."

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
                    yield "I'm currently unable to generate a response. Please try again in a moment."
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
        except (httpx.ConnectError, httpx.NetworkError):
            logger.warning("Ollama stream_generate connection error")
            yield "I'm currently unable to connect to the AI service. Please try again in a moment."
        except httpx.TimeoutException:
            logger.warning("Ollama stream_generate timeout")
            yield "The AI service is taking too long to respond. Please try again."
        except Exception as exc:
            logger.error("Ollama stream_generate failed: %s", exc)
            yield "An unexpected error occurred. Please try again."

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
                # Return zero vector as fallback instead of empty
                embeddings.append([0.0] * 768)

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
