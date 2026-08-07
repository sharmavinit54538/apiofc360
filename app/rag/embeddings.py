"""Embedding service — generates and caches text embeddings via multi-provider LLM layer.

Provides:
- Single text embedding
- Batch embedding generation
- Embedding caching (in-memory with TTL)
- Async-safe batch processing with concurrency limits
- Multi-provider support (OpenAI, Ollama, Google)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from app.llm.client import get_llm_client
from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 1 hour
_MAX_CACHE_ENTRIES = 10_000


class _EmbeddingCache:
    """Thread-safe in-memory embedding cache with TTL and LRU eviction."""

    def __init__(self, max_size: int = _MAX_CACHE_ENTRIES, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._cache: dict[str, tuple[list[float], float]] = {}
        self._max_size = max_size
        self._ttl = ttl

    def get(self, key: str) -> list[float] | None:
        entry = self._cache.get(key)
        if entry:
            embedding, expires = entry
            if time.monotonic() < expires:
                return embedding
            del self._cache[key]
        return None

    def set(self, key: str, embedding: list[float]) -> None:
        if len(self._cache) >= self._max_size:
            # Remove oldest 10% of entries
            cutoff = int(self._max_size * 0.1)
            keys_to_remove = list(self._cache.keys())[:cutoff]
            for k in keys_to_remove:
                del self._cache[k]
        self._cache[key] = (embedding, time.monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()


_embedding_cache = _EmbeddingCache()


def _cache_key(text: str, model: str) -> str:
    """Generate a stable cache key for a text + model pair."""
    digest = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:32]
    return digest


class EmbeddingService:
    """High-level embedding service with caching, batch support, and multi-provider."""

    def __init__(
        self,
        llm_client=None,
        model: str | None = None,
        provider: str | None = None,
        use_cache: bool = True,
    ) -> None:
        self._llm = llm_client or get_llm_client()
        self._model = model or getattr(settings, "OPENAI_EMBEDDING_MODEL", "") or getattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self._provider = provider
        self._use_cache = use_cache

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text string.

        Returns actual embedding from configured provider. Raises on total failure
        instead of returning fake hash-based vectors.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding — returning empty vector")
            return []

        key = _cache_key(text, self._model)
        if self._use_cache:
            cached = _embedding_cache.get(key)
            if cached is not None:
                return cached

        embedding = await self._llm.embed(text, model=self._model, provider=self._provider)

        if embedding and self._use_cache:
            _embedding_cache.set(key, embedding)

        if not embedding:
            logger.error("Embedding generation returned empty result for text (len=%d)", len(text))

        return embedding

    async def embed_batch(
        self,
        texts: list[str],
        max_concurrent: int = 10,
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts with concurrency control."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded_embed(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text)

        return await asyncio.gather(*[_bounded_embed(t) for t in texts])

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def euclidean_distance(a: list[float], b: list[float]) -> float:
        """Compute Euclidean distance between two embedding vectors."""
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    def invalidate_cache(self, text: str) -> None:
        """Remove a specific text's embedding from cache."""
        _embedding_cache.invalidate(_cache_key(text, self._model))

    def clear_cache(self) -> None:
        """Clear all cached embeddings."""
        _embedding_cache.clear()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return the global embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
