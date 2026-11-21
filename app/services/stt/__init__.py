"""STT Service Package."""

from __future__ import annotations

from app.services.stt.base import (
    STTProviderBase,
    STTProviderConfig,
    STTProviderCapability,
    TranscriptionResult,
    StreamingTranscriptionResult,
    MockSTTProvider,
)
from app.services.stt.providers import (
    DeepgramSTTProvider,
    WhisperSTTProvider,
    GoogleCloudSTTProvider,
    get_stt_provider,
    get_stt_router,
    get_available_stt_providers,
)
from app.services.stt.service import STTInterviewService, STTServiceFactory

__all__ = [
    "STTProviderBase",
    "STTProviderConfig",
    "STTProviderCapability",
    "TranscriptionResult",
    "StreamingTranscriptionResult",
    "MockSTTProvider",
    "DeepgramSTTProvider",
    "WhisperSTTProvider",
    "GoogleCloudSTTProvider",
    "get_stt_provider",
    "get_stt_router",
    "get_available_stt_providers",
    "STTInterviewService",
    "STTServiceFactory",
]