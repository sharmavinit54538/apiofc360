"""Ollama service health check and model availability checks."""

from __future__ import annotations

import logging
from typing import Any

from app.llm.client.base import LLMClientBase

logger = logging.getLogger(__name__)


class LLMHealthMixin(LLMClientBase):
    """Verifies Ollama service connectivity and model pulls."""

    async def health_check(self) -> dict[str, Any]:
        """Verify Ollama is reachable and return available models."""
        try:
            res = await self._client.get("/api/tags")
            if res.status_code == 200:
                data = res.json()
                models = [m["name"] for m in data.get("models", [])]
                return {"healthy": True, "models": models}
        except Exception as exc:
            logger.warning("Ollama health check failed: %s", exc)
        return {"healthy": False, "models": []}

    async def is_model_available(self, model: str) -> bool:
        """Return True if the requested model is pulled in Ollama."""
        info = await self.health_check()
        if not info["healthy"]:
            return False
        return any(m.startswith(model.split(":")[0]) for m in info["models"])
