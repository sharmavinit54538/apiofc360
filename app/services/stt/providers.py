"""STT Provider implementations and registry."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.services.stt.base import (
    MockSTTProvider,
    STTProviderBase,
    STTProviderCapability,
    STTProviderConfig,
    StreamingTranscriptionResult,
    TranscriptionResult,
)

logger = logging.getLogger(__name__)


class DeepgramSTTProvider(STTProviderBase):
    """Deepgram STT provider for real-time speech recognition."""

    def __init__(self, config: STTProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                STTProviderCapability.REALTIME,
                STTProviderCapability.STREAMING,
                STTProviderCapability.MULTILINGUAL,
                STTProviderCapability.SPEAKER_DIARIZATION,
                STTProviderCapability.PUNCTUATION,
                STTProviderCapability.PROFANITY_FILTER,
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh"]
        super().__init__(config)

        self._api_key = config.api_key or getattr(settings, "DEEPGRAM_API_KEY", None)
        if not self._api_key:
            logger.warning("Deepgram API key not configured")

        base_url = config.base_url or "https://api.deepgram.com"
        self._base_url = base_url.rstrip("/")
        self._timeout = config.timeout_seconds

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0, read=self._timeout),
            headers={"Authorization": f"Token {self._api_key}"} if self._api_key else {},
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )

        self._model = config.extra.get("model", "nova-2")
        self._tier = config.extra.get("tier", "enhanced")

    async def health_check(self) -> bool:
        if not self._api_key:
            self.mark_unhealthy()
            return False
        try:
            res = await self._client.get("/v1/projects", timeout=5.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("Deepgram health check failed: %s", exc)
            self.mark_unhealthy()
            return False

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> TranscriptionResult:
        if not self._api_key:
            raise RuntimeError("Deepgram API key not configured")

        language = language or self.config.default_language
        sample_rate = sample_rate or self.config.sample_rate
        encoding = encoding or self.config.encoding

        url = f"/v1/listen"
        params = {
            "model": self._model,
            "language": language,
            "sample_rate": sample_rate,
            "encoding": encoding,
            "punctuate": "true",
            "profanity_filter": "true",
            "diarize": "true" if STTProviderCapability.SPEAKER_DIARIZATION in self.config.capabilities else "false",
            "smart_format": "true",
        }

        t0 = time.perf_counter()
        try:
            res = await self._client.post(
                url,
                params=params,
                content=audio_data,
                headers={"Content-Type": f"audio/{encoding}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise RuntimeError("Deepgram transcription timed out")
        except Exception as exc:
            logger.error("Deepgram transcription error: %s", exc)
            raise

        if res.status_code != 200:
            logger.error("Deepgram error: %s - %s", res.status_code, res.text)
            raise RuntimeError(f"Deepgram transcription failed: {res.status_code}")

        data = res.json()
        latency_ms = (time.perf_counter() - t0) * 1000

        results = data.get("results", {})
        channels = results.get("channels", [])
        if not channels:
            return TranscriptionResult(
                text="",
                language=language,
                confidence=0.0,
                duration_seconds=0.0,
            )

        channel = channels[0]
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return TranscriptionResult(
                text="",
                language=language,
                confidence=0.0,
                duration_seconds=0.0,
            )

        best = alternatives[0]
        transcript = best.get("transcript", "")
        confidence = best.get("confidence", 0.0)
        words = best.get("words", [])

        # Calculate duration from words if available
        duration = 0.0
        if words:
            duration = words[-1].get("end", 0.0)

        return TranscriptionResult(
            text=transcript,
            language=language,
            confidence=confidence,
            duration_seconds=duration,
            words=words,
            is_final=True,
            metadata={"latency_ms": latency_ms, "provider": "deepgram"},
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
        """Stream audio to Deepgram for real-time transcription."""
        if not self._api_key:
            raise RuntimeError("Deepgram API key not configured")

        language = language or self.config.default_language
        sample_rate = sample_rate or self.config.sample_rate
        encoding = encoding or self.config.encoding

        # Deepgram real-time streaming uses WebSocket
        # For HTTP API, we simulate streaming by sending chunks
        ws_url = "wss://api.deepgram.com/v1/listen"
        params = {
            "model": self._model,
            "language": language,
            "sample_rate": sample_rate,
            "encoding": encoding,
            "punctuate": "true",
            "interim_results": "true" if interim_results else "false",
            "diarize": "true" if STTProviderCapability.SPEAKER_DIARIZATION in self.config.capabilities else "false",
        }

        # Note: Real implementation would use WebSocket connection
        # Here we simulate by accumulating audio and sending chunks
        buffer = bytearray()
        chunk_size = sample_rate * 2  # 1 second of 16-bit audio
        start_time = time.perf_counter()

        async for chunk in audio_stream:
            buffer.extend(chunk)
            if len(buffer) >= chunk_size:
                # Process chunk
                chunk_data = bytes(buffer)
                buffer.clear()

                elapsed = time.perf_counter() - start_time
                try:
                    # Send to Deepgram batch endpoint (simulated streaming)
                    res = await self._client.post(
                        "/v1/listen",
                        params={
                            "model": self._model,
                            "language": language,
                            "sample_rate": sample_rate,
                            "encoding": encoding,
                            "punctuate": "true",
                        },
                        content=chunk_data,
                        headers={"Content-Type": f"audio/{encoding}"},
                        timeout=self._timeout,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        results = data.get("results", {})
                        channels = results.get("channels", [])
                        if channels:
                            alternatives = channels[0].get("alternatives", [])
                            if alternatives:
                                best = alternatives[0]
                                yield StreamingTranscriptionResult(
                                    text=best.get("transcript", ""),
                                    is_final=False,
                                    confidence=best.get("confidence", 0.0),
                                    start_time=elapsed - 1.0,
                                    end_time=elapsed,
                                    language=language,
                                    words=best.get("words", []),
                                )
                except Exception as exc:
                    logger.warning("Streaming transcription chunk failed: %s", exc)

        # Process remaining buffer
        if buffer:
            try:
                elapsed = time.perf_counter() - start_time
                res = await self._client.post(
                    "/v1/listen",
                    params={
                        "model": self._model,
                        "language": language,
                        "sample_rate": sample_rate,
                        "encoding": encoding,
                        "punctuate": "true",
                    },
                    content=bytes(buffer),
                    headers={"Content-Type": f"audio/{encoding}"},
                    timeout=self._timeout,
                )
                if res.status_code == 200:
                    data = res.json()
                    results = data.get("results", {})
                    channels = results.get("channels", [])
                    if channels:
                        alternatives = channels[0].get("alternatives", [])
                        if alternatives:
                            best = alternatives[0]
                            yield StreamingTranscriptionResult(
                                text=best.get("transcript", ""),
                                is_final=True,
                                confidence=best.get("confidence", 0.0),
                                start_time=time.perf_counter() - start_time - 1.0,
                                end_time=time.perf_counter() - start_time,
                                language=language,
                                words=best.get("words", []),
                            )
            except Exception as exc:
                logger.warning("Final streaming chunk failed: %s", exc)

    async def close(self) -> None:
        await self._client.aclose()


class WhisperSTTProvider(STTProviderBase):
    """OpenAI Whisper STT provider (local or API)."""

    def __init__(self, config: STTProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                STTProviderCapability.BATCH,
                STTProviderCapability.MULTILINGUAL,
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh", "ar", "ru"]
        super().__init__(config)

        self._api_key = config.api_key or getattr(settings, "OPENAI_API_KEY", None)
        self._base_url = config.base_url or "https://api.openai.com/v1"
        self._model = config.extra.get("model", "whisper-1")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
        )

    async def health_check(self) -> bool:
        if not self._api_key:
            self.mark_unhealthy()
            return False
        try:
            res = await self._client.get("/models", timeout=5.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("Whisper health check failed: %s", exc)
            self.mark_unhealthy()
            return False

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> TranscriptionResult:
        if not self._api_key:
            raise RuntimeError("OpenAI API key not configured for Whisper")

        language = language or self.config.default_language

        t0 = time.perf_counter()
        try:
            files = {"file": ("audio.wav", audio_data, "audio/wav")}
            data = {
                "model": self._model,
                "language": language,
                "response_format": "verbose_json",
                "temperature": 0.0,
            }
            if language:
                data["language"] = language

            res = await self._client.post(
                "/audio/transcriptions",
                files=files,
                data=data,
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.error("Whisper transcription error: %s", exc)
            raise

        if res.status_code != 200:
            logger.error("Whisper error: %s - %s", res.status_code, res.text)
            raise RuntimeError(f"Whisper transcription failed: {res.status_code}")

        result = res.json()
        latency_ms = (time.perf_counter() - t0) * 1000

        return TranscriptionResult(
            text=result.get("text", ""),
            language=result.get("language", language),
            confidence=1.0,  # Whisper doesn't return confidence
            duration_seconds=result.get("duration", 0.0),
            words=result.get("words", []),
            is_final=True,
            metadata={"latency_ms": latency_ms, "provider": "whisper"},
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
        """Whisper doesn't support native streaming; accumulate and batch."""
        buffer = bytearray()
        chunk_duration = 5.0  # seconds
        chunk_size = 16000 * 2 * int(chunk_duration)  # 16-bit, 16kHz

        async for chunk in audio_stream:
            buffer.extend(chunk)
            if len(buffer) >= chunk_size:
                chunk_data = bytes(buffer)
                buffer.clear()
                try:
                    result = await self.transcribe(
                        chunk_data,
                        language=language,
                        sample_rate=sample_rate,
                        encoding=encoding,
                    )
                    yield StreamingTranscriptionResult(
                        text=result.text,
                        is_final=True,
                        confidence=result.confidence,
                        start_time=0,
                        end_time=result.duration_seconds,
                        language=result.language,
                        words=result.words,
                    )
                except Exception as exc:
                    logger.warning("Whisper streaming chunk failed: %s", exc)

        if buffer:
            try:
                result = await self.transcribe(
                    bytes(buffer),
                    language=language,
                    sample_rate=sample_rate,
                    encoding=encoding,
                )
                yield StreamingTranscriptionResult(
                    text=result.text,
                    is_final=True,
                    confidence=result.confidence,
                    start_time=0,
                    end_time=result.duration_seconds,
                    language=result.language,
                    words=result.words,
                )
            except Exception as exc:
                logger.warning("Whisper final chunk failed: %s", exc)

    async def close(self) -> None:
        await self._client.aclose()


class GoogleCloudSTTProvider(STTProviderBase):
    """Google Cloud Speech-to-Text provider."""

    def __init__(self, config: STTProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                STTProviderCapability.REALTIME,
                STTProviderCapability.STREAMING,
                STTProviderCapability.MULTILINGUAL,
                STTProviderCapability.SPEAKER_DIARIZATION,
                STTProviderCapability.PUNCTUATION,
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh", "ar"]
        super().__init__(config)

        self._credentials_path = config.extra.get("credentials_path")
        self._project_id = config.extra.get("project_id")
        self._model = config.extra.get("model", "latest_long")
        self._use_enhanced = config.extra.get("use_enhanced", True)

        # Initialize Google Cloud client lazily
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import speech
            if self._credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials_path
            self._client = speech.SpeechClient()
        return self._client

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            # Simple health check - list recognizers
            self._healthy = True
            return True
        except Exception as exc:
            logger.warning("Google Cloud STT health check failed: %s", exc)
            self.mark_unhealthy()
            return False

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> TranscriptionResult:
        from google.cloud import speech

        client = self._get_client()
        language = language or self.config.default_language
        sample_rate = sample_rate or self.config.sample_rate

        audio = speech.RecognitionAudio(content=audio_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=language,
            enable_automatic_punctuation=True,
            enable_speaker_diarization=STTProviderCapability.SPEAKER_DIARIZATION in self.config.capabilities,
            diarization_speaker_count=2,
            use_enhanced=self._use_enhanced,
            model=self._model,
        )

        t0 = time.perf_counter()
        try:
            response = await asyncio.to_thread(client.recognize, config=config, audio=audio)
        except Exception as exc:
            logger.error("Google Cloud STT transcription error: %s", exc)
            raise

        latency_ms = (time.perf_counter() - t0) * 1000

        if not response.results:
            return TranscriptionResult(
                text="",
                language=language,
                confidence=0.0,
                duration_seconds=0.0,
            )

        best = response.results[0].alternatives[0]
        transcript = best.transcript
        confidence = best.confidence
        words = [
            {
                "word": w.word,
                "start_time": w.start_time.total_seconds() if w.start_time else 0,
                "end_time": w.end_time.total_seconds() if w.end_time else 0,
                "speaker_tag": w.speaker_tag if hasattr(w, "speaker_tag") else 0,
            }
            for w in best.words
        ] if best.words else []

        duration = words[-1]["end_time"] if words else 0.0

        return TranscriptionResult(
            text=transcript,
            language=language,
            confidence=confidence,
            duration_seconds=duration,
            words=words,
            is_final=True,
            metadata={"latency_ms": latency_ms, "provider": "google_cloud"},
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
        """Google Cloud STT streaming via gRPC."""
        from google.cloud import speech

        client = self._get_client()
        language = language or self.config.default_language
        sample_rate = sample_rate or self.config.sample_rate

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=language,
            enable_automatic_punctuation=True,
            enable_speaker_diarization=STTProviderCapability.SPEAKER_DIARIZATION in self.config.capabilities,
            diarization_speaker_count=2,
            use_enhanced=self._use_enhanced,
            model=self._model,
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=interim_results,
            single_utterance=False,
        )

        def request_generator():
            yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
            for chunk in audio_stream:
                yield speech.StreamingRecognizeRequest(audio_content=chunk)

        try:
            responses = client.streaming_recognize(request_generator())
            start_time = time.perf_counter()
            for response in responses:
                for result in response.results:
                    if result.alternatives:
                        best = result.alternatives[0]
                        is_final = result.is_final
                        elapsed = time.perf_counter() - start_time
                        yield StreamingTranscriptionResult(
                            text=best.transcript,
                            is_final=is_final,
                            confidence=best.confidence,
                            start_time=elapsed - 1.0 if not is_final else elapsed - 2.0,
                            end_time=elapsed,
                            language=language,
                            words=[{"word": w.word, "start_time": w.start_time.total_seconds(), "end_time": w.end_time.total_seconds()} for w in best.words] if best.words else [],
                        )
        except Exception as exc:
            logger.error("Google Cloud STT streaming error: %s", exc)
            raise

    async def close(self) -> None:
        pass


# Provider registry
_STT_PROVIDERS: dict[str, STTProviderBase] = {}


def get_stt_provider(name: str = "deepgram") -> STTProviderBase:
    """Get or create an STT provider instance."""
    global _STT_PROVIDERS

    if name in _STT_PROVIDERS:
        return _STT_PROVIDERS[name]

    provider = _create_provider(name)
    _STT_PROVIDERS[name] = provider
    return provider


def _create_provider(name: str) -> STTProviderBase:
    """Create an STT provider instance by name."""
    name = name.lower()

    if name == "mock":
        config = STTProviderConfig(
            name="mock",
            base_url="",
            supported_languages=["en", "hi"],
            capabilities={STTProviderCapability.REALTIME, STTProviderCapability.STREAMING, STTProviderCapability.BATCH},
        )
        return MockSTTProvider(config)

    elif name == "deepgram":
        config = STTProviderConfig(
            name="deepgram",
            base_url="https://api.deepgram.com",
            api_key=getattr(settings, "DEEPGRAM_API_KEY", None),
            default_language="en",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh"],
            capabilities={
                STTProviderCapability.REALTIME,
                STTProviderCapability.STREAMING,
                STTProviderCapability.MULTILINGUAL,
                STTProviderCapability.SPEAKER_DIARIZATION,
                STTProviderCapability.PUNCTUATION,
                STTProviderCapability.PROFANITY_FILTER,
            },
            extra={
                "model": getattr(settings, "DEEPGRAM_MODEL", "nova-2"),
                "tier": "enhanced",
            },
            timeout_seconds=30.0,
        )
        return DeepgramSTTProvider(config)

    elif name == "whisper":
        config = STTProviderConfig(
            name="whisper",
            base_url="https://api.openai.com/v1",
            api_key=getattr(settings, "OPENAI_API_KEY", None),
            default_language="en",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh", "ar", "ru"],
            capabilities={
                STTProviderCapability.BATCH,
                STTProviderCapability.MULTILINGUAL,
            },
            extra={
                "model": getattr(settings, "WHISPER_MODEL", "whisper-1"),
            },
            timeout_seconds=60.0,
        )
        return WhisperSTTProvider(config)

    elif name == "google_cloud":
        config = STTProviderConfig(
            name="google_cloud",
            base_url="",
            api_key=None,
            default_language="en",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh", "ar"],
            capabilities={
                STTProviderCapability.REALTIME,
                STTProviderCapability.STREAMING,
                STTProviderCapability.MULTILINGUAL,
                STTProviderCapability.SPEAKER_DIARIZATION,
                STTProviderCapability.PUNCTUATION,
            },
            extra={
                "credentials_path": getattr(settings, "GOOGLE_CLOUD_CREDENTIALS_PATH", None),
                "project_id": getattr(settings, "GOOGLE_CLOUD_PROJECT_ID", None),
                "model": "latest_long",
                "use_enhanced": True,
            },
            timeout_seconds=60.0,
        )
        return GoogleCloudSTTProvider(config)

    else:
        logger.warning("Unknown STT provider '%s', falling back to mock", name)
        return _create_provider("mock")


def get_available_stt_providers() -> list[str]:
    """Get list of available STT provider names."""
    return ["mock", "deepgram", "whisper", "google_cloud"]


async def get_stt_router() -> STTProviderBase:
    """Get the default STT provider (first available)."""
    for name in ["deepgram", "whisper", "google_cloud", "mock"]:
        try:
            provider = get_stt_provider(name)
            if await provider.health_check():
                return provider
        except Exception:
            continue
    # Fallback to mock
    return get_stt_provider("mock")