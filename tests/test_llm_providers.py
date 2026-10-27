"""Unit tests for LLM Provider Registry and Health Recovery (Ollama-only)."""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime

from app.llm.providers.base import (
    LLMProviderBase,
    ProviderConfig,
    ProviderCapability,
    LLMResponse,
    EmbeddingResponse,
    HEALTH_COOLDOWN_SECONDS,
)
from app.llm.providers.registry import ProviderRegistry
from app.llm.router import LLMRouter


def _create_mock_settings(**overrides):
    """Create a mock settings object with all required attributes."""
    defaults = {
        "OLLAMA_ENABLED": True,
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen3:30b",
        "OLLAMA_DEFAULT_MODEL": "qwen3:30b",
        "OLLAMA_EMBEDDING_MODEL": "nomic-embed-text",
        "OLLAMA_TIMEOUT": 60,
        "OLLAMA_TIMEOUT_SECONDS": 60,
        "OLLAMA_PRIORITY": 1,
        "OLLAMA_KEEP_ALIVE": "30m",
        "OLLAMA_TOP_P": 0.9,
        "OLLAMA_NUM_PREDICT": 2048,
        "OLLAMA_MAX_CONNECTIONS": 50,
    }
    defaults.update(overrides)
    
    # Create a simple object instead of MagicMock to avoid attribute access issues
    class MockSettings:
        pass
    
    mock_settings = MockSettings()
    for key, value in defaults.items():
        setattr(mock_settings, key, value)
    return mock_settings


class MockProvider(LLMProviderBase):
    """Mock provider for testing."""
    
    def __init__(self, name: str, healthy: bool = True, should_fail: bool = False):
        config = ProviderConfig(
            name=name,
            default_model="test-model",
            capabilities={ProviderCapability.CHAT, ProviderCapability.EMBEDDING},
            priority=10,
        )
        super().__init__(config)
        self._healthy = healthy
        self._should_fail = should_fail
        self.chat_called = False
        self.embed_called = False
        self.health_check_called = False
        # Track if mark_unhealthy was called
        self._marked_unhealthy = False

    async def health_check(self) -> bool:
        self.health_check_called = True
        if self._should_fail:
            return False
        return self._healthy

    async def chat(self, messages, *, model=None, temperature=0.3, max_tokens=2048, json_mode=False, tools=None):
        self.chat_called = True
        if self._should_fail:
            self.mark_unhealthy()
            raise Exception(f"Provider {self.name} failed")
        return LLMResponse(content="test response", model="test-model", provider=self.name)

    async def stream_chat(self, messages, *, model=None, temperature=0.3, max_tokens=2048):
        yield "test"

    async def embed(self, texts, *, model=None):
        self.embed_called = True
        if self._should_fail:
            raise Exception(f"Provider {self.name} failed")
        return EmbeddingResponse(embeddings=[[0.1] * 10 for _ in texts], model="test-model", provider=self.name)

    def mark_unhealthy(self):
        super().mark_unhealthy()
        self._marked_unhealthy = True


class TestProviderRegistry:
    """Test ProviderRegistry - Ollama only."""

    def test_registry_registers_ollama_when_enabled(self):
        """Ollama should register when OLLAMA_ENABLED=true."""
        mock_settings = _create_mock_settings(OLLAMA_ENABLED=True)

        with patch("app.llm.providers.registry.settings", mock_settings):
            registry = ProviderRegistry()
            registry.initialise()

            providers = registry.get_all()
            assert len(providers) == 1
            assert "ollama" in providers

    def test_registry_does_not_register_ollama_when_disabled(self):
        """Ollama should not register when OLLAMA_ENABLED=false."""
        mock_settings = _create_mock_settings(OLLAMA_ENABLED=False)

        with patch("app.llm.providers.registry.settings", mock_settings):
            registry = ProviderRegistry()
            registry.initialise()

            providers = registry.get_all()
            assert len(providers) == 0

    def test_registry_warns_when_no_providers(self, caplog):
        """Registry should log warning when zero providers registered."""
        mock_settings = _create_mock_settings(OLLAMA_ENABLED=False)

        with patch("app.llm.providers.registry.settings", mock_settings):
            registry = ProviderRegistry()
            registry.initialise()

            assert "No LLM providers registered" in caplog.text


class TestProviderHealthRecovery:
    """Test provider health recovery with half-open cooldown."""

    @pytest.mark.asyncio
    async def test_provider_marks_unhealthy_on_failure(self):
        """Provider should mark unhealthy when chat fails."""
        provider = MockProvider("ollama", healthy=True, should_fail=True)
        
        # Initial state
        assert provider.is_healthy is True
        
        # Trigger failure
        try:
            await provider.chat([{"role": "user", "content": "test"}])
        except Exception:
            pass
        
        # Should be marked unhealthy
        assert provider.is_healthy is False

    @pytest.mark.asyncio
    async def test_provider_recovery_after_cooldown(self):
        """Provider should allow recovery attempt after 30s cooldown (half-open)."""
        provider = MockProvider("ollama", healthy=False)
        provider._unhealthy_since = time.time() - 35  # 35 seconds ago
        
        # Should allow attempt (half-open)
        assert provider.is_healthy is True
        
        # Successful operation should mark healthy
        provider._healthy = False  # Reset to test mark_healthy
        provider.mark_healthy()
        assert provider.is_healthy is True

    @pytest.mark.asyncio
    async def test_provider_blocked_before_cooldown(self):
        """Provider should block attempts before 30s cooldown."""
        provider = MockProvider("ollama", healthy=False)
        provider._unhealthy_since = time.time() - 10  # 10 seconds ago
        
        # Should still be blocked
        assert provider.is_healthy is False


class TestRouterHalfOpenRecovery:
    """Test router half-open recovery when all providers unhealthy."""

    @pytest.mark.asyncio
    async def test_router_tries_all_providers_when_none_healthy(self):
        """Router should try all registered providers when none are healthy (half-open)."""
        mock_registry = MagicMock()
        
        # Create mock providers - all unhealthy
        provider1 = MockProvider("ollama", healthy=False)
        
        # Make registry return empty healthy list but all providers in get_by_priority
        mock_registry.get_healthy.return_value = []
        mock_registry.get_by_priority.return_value = [provider1]
        mock_registry.get.return_value = None
        
        router = LLMRouter()
        router._registry = mock_registry
        
        # Should try all providers (half-open)
        candidates = router._resolve_provider(capability=ProviderCapability.CHAT, allow_half_open=True)
        assert len(candidates) == 1
        assert provider1 in candidates

    @pytest.mark.asyncio
    async def test_router_skips_half_open_when_disabled(self):
        """Router should not try unhealthy providers when half-open disabled."""
        mock_registry = MagicMock()
        
        provider1 = MockProvider("ollama", healthy=False)
        provider2 = MockProvider("ollama2", healthy=True)
        
        mock_registry.get_healthy.return_value = [provider2]
        mock_registry.get_by_priority.return_value = [provider1, provider2]
        
        router = LLMRouter()
        router._registry = mock_registry
        
        candidates = router._resolve_provider(capability=ProviderCapability.CHAT, allow_half_open=False)
        assert len(candidates) == 1
        assert provider2 in candidates
        assert provider1 not in candidates

    @pytest.mark.asyncio
    async def test_router_prioritizes_requested_provider(self):
        """Router should try requested provider first even if unhealthy (half-open)."""
        mock_registry = MagicMock()
        
        requested = MockProvider("ollama", healthy=False)
        healthy = MockProvider("ollama2", healthy=True)
        
        mock_registry.get.return_value = requested
        mock_registry.get_healthy.return_value = [healthy]
        mock_registry.get_by_priority.return_value = [requested, healthy]
        
        router = LLMRouter()
        router._registry = mock_registry
        
        candidates = router._resolve_provider(provider_name="ollama", capability=ProviderCapability.CHAT, allow_half_open=True)
        assert candidates[0] == requested
        assert candidates[1] == healthy


class TestGracefulDegradation:
    """Test graceful degradation when all providers fail."""

    @pytest.mark.asyncio
    async def test_chat_returns_empty_when_all_providers_fail(self):
        """Chat should return empty response when all providers fail."""
        mock_registry = MagicMock()
        
        provider1 = MockProvider("ollama", should_fail=True)
        
        mock_registry.get_healthy.return_value = [provider1]
        mock_registry.get_by_priority.return_value = [provider1]
        
        router = LLMRouter()
        router._registry = mock_registry
        
        response = await router.chat([{"role": "user", "content": "test"}])
        
        assert response.content == ""
        assert response.provider == "none"

    @pytest.mark.asyncio
    async def test_router_returns_last_response_when_all_return_empty(self):
        """Router should return last response when all providers return empty content."""
        mock_registry = MagicMock()
        
        provider1 = MockProvider("ollama", healthy=True)
        provider1._healthy = True
        
        # Make provider return empty content
        async def empty_chat(*args, **kwargs):
            return LLMResponse(content="", model="test", provider="ollama")
        provider1.chat = empty_chat
        
        mock_registry.get_healthy.return_value = [provider1]
        mock_registry.get_by_priority.return_value = [provider1]
        
        router = LLMRouter()
        router._registry = mock_registry
        
        response = await router.chat([{"role": "user", "content": "test"}])
        
        assert response.content == ""
        assert response.provider == "ollama"


class TestOllamaOnlyRegistration:
    """Test that only Ollama can be registered - no cloud providers."""

    def test_no_cloud_providers_registered(self):
        """Verify cloud providers cannot be registered."""
        mock_settings = _create_mock_settings(
            OLLAMA_ENABLED=True,
            # These should be ignored
            OPENAI_API_KEY="sk-test",
            ANTHROPIC_API_KEY="sk-ant-test",
            GOOGLE_AI_API_KEY="google-test",
            OPENROUTER_API_KEY="openrouter-test",
        )

        with patch("app.llm.providers.registry.settings", mock_settings):
            registry = ProviderRegistry()
            registry.initialise()

            providers = registry.get_all()
            assert len(providers) == 1
            assert "ollama" in providers
            assert "openai" not in providers
            assert "anthropic" not in providers
            assert "google" not in providers
            assert "openrouter" not in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])