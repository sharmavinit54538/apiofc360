"""Provider registry — auto-discovers and manages all configured LLM providers."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.llm.providers.base import (
    LLMProviderBase,
    ProviderCapability,
    ProviderConfig,
)

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Discovers, initialises, and manages all configured LLM providers.

    Providers are auto-enabled based on presence of API keys in settings.
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProviderBase] = {}
        self._initialised = False

    def _build_configs(self) -> list[ProviderConfig]:
        """Build provider configurations from application settings (Ollama ONLY)."""
        configs: list[ProviderConfig] = []

        # Ollama — primary and exclusive LLM provider
        configs.append(ProviderConfig(
            name="ollama",
            base_url=getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "OLLAMA_HOST", "http://127.0.0.1:11434")),
            default_model=getattr(settings, "OLLAMA_MODEL", getattr(settings, "OLLAMA_DEFAULT_MODEL", "llama3.1")),
            embedding_model=getattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
            max_retries=3,
            timeout_seconds=getattr(settings, "OLLAMA_TIMEOUT", getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 60)),
            rate_limit_rpm=999,
            enabled=getattr(settings, "OLLAMA_ENABLED", True),
            priority=getattr(settings, "OLLAMA_PRIORITY", 1),
            extra={
                "keep_alive": getattr(settings, "OLLAMA_KEEP_ALIVE", "30m"),
                "top_p": getattr(settings, "OLLAMA_TOP_P", 0.9),
                "num_predict": getattr(settings, "OLLAMA_NUM_PREDICT", 2048),
                "max_connections": getattr(settings, "OLLAMA_MAX_CONNECTIONS", 50),
            },
        ))

        return configs


    def _create_provider(self, config: ProviderConfig) -> LLMProviderBase:
        """Factory: instantiate the correct provider class."""
        from app.llm.providers.ollama_provider import OllamaProvider
        from app.llm.providers.openai_provider import OpenAIProvider
        from app.llm.providers.anthropic_provider import AnthropicProvider
        from app.llm.providers.google_provider import GoogleProvider
        from app.llm.providers.openrouter_provider import OpenRouterProvider

        factories: dict[str, type[LLMProviderBase]] = {
            "ollama": OllamaProvider,
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "google": GoogleProvider,
            "openrouter": OpenRouterProvider,
        }

        factory = factories.get(config.name)
        if not factory:
            raise ValueError(f"Unknown provider: {config.name}")
        return factory(config)

    def initialise(self) -> None:
        """Build and register all enabled providers from settings."""
        if self._initialised:
            return

        configs = self._build_configs()
        for cfg in configs:
            if not cfg.enabled:
                continue
            try:
                provider = self._create_provider(cfg)
                self._providers[cfg.name] = provider
                logger.info("Registered LLM provider: %s (priority=%d, model=%s)", cfg.name, cfg.priority, cfg.default_model)
            except Exception as exc:
                logger.error("Failed to initialise provider '%s': %s", cfg.name, exc)

        self._initialised = True
        logger.info("Provider registry initialised with %d providers: %s", len(self._providers), list(self._providers.keys()))

    def get(self, name: str) -> LLMProviderBase | None:
        """Get a specific provider by name."""
        self._ensure_init()
        return self._providers.get(name)

    def get_all(self) -> dict[str, LLMProviderBase]:
        """Get all registered providers."""
        self._ensure_init()
        return dict(self._providers)

    def get_by_priority(self, capability: ProviderCapability | None = None) -> list[LLMProviderBase]:
        """Get providers sorted by priority (lowest number = highest priority).

        Optionally filter by capability.
        """
        self._ensure_init()
        providers = list(self._providers.values())

        if capability:
            providers = [p for p in providers if p.supports(capability)]

        return sorted(providers, key=lambda p: p.config.priority)

    def get_healthy(self, capability: ProviderCapability | None = None) -> list[LLMProviderBase]:
        """Get only healthy providers, sorted by priority."""
        return [p for p in self.get_by_priority(capability) if p.is_healthy]

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all providers and return results."""
        self._ensure_init()
        results = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    async def close_all(self) -> None:
        """Close all provider HTTP clients."""
        for provider in self._providers.values():
            try:
                await provider.close()
            except Exception as exc:
                logger.warning("Error closing provider %s: %s", provider.name, exc)

    def _ensure_init(self) -> None:
        if not self._initialised:
            self.initialise()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Return the global provider registry singleton."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        _registry.initialise()
    return _registry
