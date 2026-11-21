"""TTS Service Package."""

from __future__ import annotations

from app.services.tts.base import (
    TTSProviderBase,
    TTSProviderConfig,
    TTSResult,
    StreamingTTSResult,
    MockTTSProvider,
)
from app.services.tts.providers import (
    ElevenLabsTTSProvider,
    OpenAITTSProvider,
    GoogleCloudTTSProvider,
    AzureTTSProvider,
    CoquiTTSProvider,
    get_tts_provider,
    get_tts_router,
    get_available_tts_providers,
)
from app.services.tts.service import TTSInterviewService, TTSServiceFactory

__all__ = [
    "TTSProviderBase",
    "TTSProviderConfig",
    "TTSResult",
    "StreamingTTSResult",
    "MockTTSProvider",
    "ElevenLabsTTSProvider",
    "OpenAITTSProvider",
    "GoogleCloudTTSProvider",
    "AzureTTSProvider",
    "CoquiTTSProvider",
    "get_tts_provider",
    "get_tts_router",
    "get_available_tts_providers",
    "TTSInterviewService",
    "TTSServiceFactory",
]