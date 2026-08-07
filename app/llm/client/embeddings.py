"""Ollama text embedding generation utilities."""

from __future__ import annotations

import asyncio
import logging

from app.llm.client.base import LLMClientBase

logger = logging.getLogger(__name__)


class LLMEmbeddingsMixin(LLMClientBase):
    """Methods for generating embeddings (including batching and fallback)."""

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
    ) -> list[float]:
        """Generate a vector embedding for the given text."""
        chosen_model = model or self._embedding_model
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
                    return embedding
        except Exception as exc:
            logger.warning("Ollama embed failed, using fallback: %s", exc)

        return self._fallback_embedding(text)

    async def embed_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        tasks = [self.embed(t, model=model) for t in texts]
        return await asyncio.gather(*tasks)

    @staticmethod
    def _fallback_embedding(text: str, dim: int = 768) -> list[float]:
        """Deterministic pseudo-random fallback embedding (offline mode)."""
        import hashlib
        import struct

        seed_bytes = hashlib.sha256(text.encode()).digest()
        seed = struct.unpack("<Q", seed_bytes[:8])[0]

        # LCG random number generator seeded deterministically
        lcg_a, lcg_c, lcg_m = 1664525, 1013904223, 2**32
        values: list[float] = []
        state = seed
        for _ in range(dim):
            state = (lcg_a * state + lcg_c) % lcg_m
            values.append((state / lcg_m) * 2.0 - 1.0)

        # L2-normalize
        norm = sum(v * v for v in values) ** 0.5
        if norm > 0:
            values = [v / norm for v in values]
        return values
