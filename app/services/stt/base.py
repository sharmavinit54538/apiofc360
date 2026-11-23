"""Base STT (Speech-to-Text) provider abstraction."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Optional

from app.core.config import settings


class STTProviderCapability(str, Enum):
    """Capabilities that STT providers may support."""
    REALTIME = "realtime"
    BATCH = "batch"
    STREAMING = "streaming"
    MULTILINGUAL = "multilingual"
    SPEAKER_DIARIZATION = "speaker_diarization"
    PUNCTUATION = "punctuation"
    PROFANITY_FILTER = "profanity_filter"


@dataclass
class STTProviderConfig:
    """Configuration for an STT provider."""
    name: str
    base_url: str
    api_key: Optional[str] = None
    default_language: str = "en"
    supported_languages: list[str] = None
    capabilities: set[STTProviderCapability] = None
    timeout_seconds: float = 30.0
    max_audio_duration_seconds: int = 300
    sample_rate: int = 16000
    encoding: str = "linear16"
    extra: dict = None

    def __post_init__(self):
        if self.supported_languages is None:
            self.supported_languages = ["en", "hi"]
        if self.capabilities is None:
            self.capabilities = {STTProviderCapability.REALTIME, STTProviderCapability.BATCH}
        if self.extra is None:
            self.extra = {}


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""
    text: str
    language: str
    confidence: float
    duration_seconds: float
    words: list[dict] = None
    speaker_labels: list[dict] = None
    is_final: bool = True
    metadata: dict = None


@dataclass
class StreamingTranscriptionResult:
    """Result of a streaming transcription chunk."""
    text: str
    is_final: bool
    confidence: float
    start_time: float
    end_time: float
    language: str
    words: list[dict] = None


class STTProviderBase(ABC):
    """Abstract base class for STT providers."""

    def __init__(self, config: STTProviderConfig) -> None:
        self.config = config
        self._healthy = True

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    def mark_healthy(self) -> None:
        self._healthy = True

    def mark_unhealthy(self) -> None:
        self._healthy = False

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy and available."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio data to text (batch mode)."""
        pass

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
        interim_results: bool = True,
    ) -> AsyncGenerator[StreamingTranscriptionResult, None]:
        """Transcribe streaming audio data in real-time."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the provider and release resources."""
        pass

    def supports_language(self, language: str) -> bool:
        """Check if the provider supports a given language."""
        return language in self.config.supported_languages

    def has_capability(self, capability: STTProviderCapability) -> bool:
        """Check if the provider supports a given capability."""
        return capability in self.config.capabilities


class MockSTTProvider(STTProviderBase):
    """Mock STT provider for testing and development."""

    def __init__(self, config: STTProviderConfig) -> None:
        super().__init__(config)
        self._delay = 0.1

    async def health_check(self) -> bool:
        return True

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> TranscriptionResult:
        await asyncio.sleep(self._delay)
        # Mock transcription based on audio length
        duration = len(audio_data) / (sample_rate or 16000) / 2  # rough estimate
        return TranscriptionResult(
            text="This is a mock transcription for testing purposes.",
            language=language or "en",
            confidence=0.95,
            duration_seconds=duration,
            is_final=True,
            metadata={"mock": True},
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
        interim_results: bool = True,
    ) -> AsyncGenerator[StreamingTranscriptionResult, None]:
        async for chunk in audio_stream:
            await asyncio.sleep(self._delay)
            yield StreamingTranscriptionResult(
                text="Mock streaming transcription",
                is_final=False,
                confidence=0.9,
                start_time=0.0,
                end_time=1.0,
                language=language or "en",
            )
        # Final result
        yield StreamingTranscriptionResult(
            text="Mock streaming transcription complete.",
            is_final=True,
            confidence=0.95,
            start_time=0.0,
            end_time=5.0,
            language=language or "en",
        )

    async def close(self) -> None:
        pass