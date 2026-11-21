"""Base TTS (Text-to-Speech) provider abstraction."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Optional

from app.core.config import settings


class TTSProviderCapability(str, Enum):
    """Capabilities that TTS providers may support."""
    STREAMING = "streaming"
    BATCH = "batch"
    MULTILINGUAL = "multilingual"
    VOICE_CLONING = "voice_cloning"
    SSML_SUPPORT = "ssml_support"
    SPEED_CONTROL = "speed_control"
    PITCH_CONTROL = "pitch_control"
    VOLUME_CONTROL = "volume_control"
    EMOTION_CONTROL = "emotion_control"


@dataclass
class TTSProviderConfig:
    """Configuration for a TTS provider."""
    name: str
    base_url: str
    api_key: Optional[str] = None
    default_voice: str = "default"
    default_language: str = "en"
    supported_languages: list[str] = None
    supported_voices: list[str] = None
    capabilities: set = None
    timeout_seconds: float = 30.0
    sample_rate: int = 24000
    audio_format: str = "mp3"
    extra: dict = None

    def __post_init__(self):
        if self.supported_languages is None:
            self.supported_languages = ["en", "hi"]
        if self.supported_voices is None:
            self.supported_voices = ["default"]
        if self.capabilities is None:
            self.capabilities = {"streaming", "batch"}
        if self.extra is None:
            self.extra = {}


@dataclass
class TTSResult:
    """Result of a TTS synthesis operation."""
    audio_data: bytes
    format: str
    sample_rate: int
    duration_seconds: float
    voice: str
    language: str
    metadata: dict = None


@dataclass
class StreamingTTSResult:
    """Result chunk from streaming TTS synthesis."""
    audio_chunk: bytes
    is_final: bool
    format: str
    sample_rate: int


class TTSProviderBase(ABC):
    """Abstract base class for TTS providers."""

    def __init__(self, config: TTSProviderConfig) -> None:
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
    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> TTSResult:
        """Synthesize text to speech (batch mode)."""
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Synthesize text to speech in streaming mode."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the provider and release resources."""
        pass

    def supports_language(self, language: str) -> bool:
        """Check if the provider supports a given language."""
        return language in self.config.supported_languages

    def supports_voice(self, voice: str) -> bool:
        """Check if the provider supports a given voice."""
        return voice in self.config.supported_voices

    def has_capability(self, capability: str) -> bool:
        """Check if the provider supports a given capability."""
        return capability in self.config.capabilities


class MockTTSProvider(TTSProviderBase):
    """Mock TTS provider for testing and development."""

    def __init__(self, config: TTSProviderConfig) -> None:
        super().__init__(config)
        self._delay = 0.05

    async def health_check(self) -> bool:
        return True

    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> TTSResult:
        await asyncio.sleep(self._delay)
        # Generate mock audio data (silence)
        duration = len(text) * 0.05  # rough estimate
        sample_rate = self.config.sample_rate
        num_samples = int(duration * sample_rate)
        # Generate simple sine wave as mock audio
        import math
        audio_data = bytearray()
        for i in range(num_samples):
            t = i / self.config.sample_rate
            # Generate a simple tone
            value = int(32767 * 0.1 * math.sin(2 * math.pi * 440 * t))
            audio_data.extend(value.to_bytes(2, byteorder='little', signed=True))
        
        return TTSResult(
            audio_data=bytes(audio_data),
            format=self.config.audio_format,
            sample_rate=self.config.sample_rate,
            duration_seconds=duration,
            voice=voice or self.config.default_voice,
            language=language or self.config.default_language,
            metadata={"mock": True, "text_length": len(text)},
        )

    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        import math
        words = text.split()
        chunk_size = max(1, len(words) // 5)
        
        for i in range(0, len(words), chunk_size):
            chunk_text = " ".join(words[i:i + chunk_size])
            await asyncio.sleep(self._delay)
            
            duration = len(chunk_text) * 0.05
            sample_rate = self.config.sample_rate
            num_samples = int(duration * sample_rate)
            audio_data = bytearray()
            for j in range(num_samples):
                t = j / self.config.sample_rate
                value = int(32767 * 0.1 * math.sin(2 * math.pi * 440 * t))
                audio_data.extend(value.to_bytes(2, byteorder='little', signed=True))
            
            is_final = (i + chunk_size) >= len(words)
            yield StreamingTTSResult(
                audio_chunk=bytes(audio_data),
                is_final=is_final,
                format=self.config.audio_format,
                sample_rate=self.config.sample_rate,
            )

    async def close(self) -> None:
        pass