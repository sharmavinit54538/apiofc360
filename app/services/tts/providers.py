"""TTS Provider implementations and registry."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.services.tts.base import (
    MockTTSProvider,
    TTSProviderBase,
    TTSProviderCapability,
    TTSProviderConfig,
    StreamingTTSResult,
    TTSResult,
)

logger = logging.getLogger(__name__)


class ElevenLabsTTSProvider(TTSProviderBase):
    """ElevenLabs TTS provider for high-quality voice synthesis."""

    def __init__(self, config: TTSProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                "streaming",
                "batch",
                "multilingual",
                "voice_cloning",
                "speed_control",
                "pitch_control",
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "nl", "pl", "ru", "ja", "ko", "zh"]
        if config.supported_voices is None:
            config.supported_voices = [
                "rachel", "domi", "bella", "antoni", "elli", "josh",
                "arnold", "adam", "sam", "charlie", "emily", "grace"
            ]
        super().__init__(config)

        self._api_key = config.api_key or getattr(settings, "ELEVENLABS_API_KEY", None)
        if not self._api_key:
            logger.warning("ElevenLabs API key not configured")

        base_url = config.base_url or "https://api.elevenlabs.io"
        self._base_url = base_url.rstrip("/")
        self._timeout = config.timeout_seconds

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0, read=self._timeout),
            headers={"xi-api-key": self._api_key} if self._api_key else {},
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )

        self._model = config.extra.get("model", "eleven_multilingual_v2")
        self._voice_id = config.extra.get("voice_id", "21m00Tcm4TlvDq8ikWAM")  # Default: Rachel

    async def health_check(self) -> bool:
        if not self._api_key:
            self.mark_unhealthy()
            return False
        try:
            res = await self._client.get("/v1/user", timeout=5.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("ElevenLabs health check failed: %s", exc)
            self.mark_unhealthy()
            return False

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
        if not self._api_key:
            raise RuntimeError("ElevenLabs API key not configured")

        voice_id = voice or self._voice_id
        model = self._model

        url = f"/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        t0 = time.perf_counter()
        try:
            res = await self._client.post(
                url,
                json=payload,
                headers={"Accept": "audio/mpeg"},
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.error("ElevenLabs synthesis error: %s", exc)
            raise

        if res.status_code != 200:
            logger.error("ElevenLabs error: %s - %s", res.status_code, res.text)
            raise RuntimeError(f"ElevenLabs synthesis failed: {res.status_code}")

        audio_data = res.content
        latency_ms = (time.perf_counter() - t0) * 1000

        # Estimate duration from audio size (rough)
        duration = len(text) * 0.05  # rough estimate

        return TTSResult(
            audio_data=res.content,
            format="mp3",
            sample_rate=22050,
            duration_seconds=len(text) * 0.05,
            voice=voice or "default",
            language="en",
            metadata={"latency_ms": latency_ms, "provider": "elevenlabs"},
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
        """ElevenLabs supports streaming via WebSocket."""
        # For now, use batch synthesis and chunk the result
        result = await self.synthesize(text, voice=voice, language=language, speed=speed, pitch=pitch, volume=volume)
        
        # Chunk the audio data for streaming simulation
        chunk_size = 4096
        audio_data = result.audio_data
        
        for i in range(0, len(audio_data), 4096):
            chunk = audio_data[i:i + 4096]
            await asyncio.sleep(0.01)  # Small delay to simulate streaming
            is_final = (i + 4096) >= len(result.audio_data)
            yield StreamingTTSResult(
                audio_chunk=chunk,
                is_final=(i + 4096) >= len(audio_data),
                format="mp3",
                sample_rate=22050,
            )

    async def close(self) -> None:
        await self._client.aclose()


class OpenAITTSProvider(TTSProviderBase):
    """OpenAI TTS provider (TTS-1, TTS-1-HD)."""

    def __init__(self, config: TTSProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                "batch",
                "multilingual",
                "speed_control",
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh"]
        if config.supported_voices is None:
            config.supported_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        super().__init__(config)

        self._api_key = config.api_key or getattr(settings, "OPENAI_API_KEY", None)
        if not self._api_key:
            logger.warning("OpenAI API key not configured for TTS")

        base_url = config.base_url or "https://api.openai.com/v1"
        self._base_url = base_url.rstrip("/")
        self._timeout = config.timeout_seconds

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
        )

        self._model = config.extra.get("model", "tts-1")
        self._voice = config.extra.get("voice", "alloy")

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
            logger.warning("OpenAI TTS health check failed: %s", exc)
            self.mark_unhealthy()
            return False

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
        if not self._api_key:
            raise RuntimeError("OpenAI API key not configured for TTS")

        voice_name = voice or self._voice
        model = self._model

        url = "/audio/speech"
        payload = {
            "model": model,
            "input": text,
            "voice": voice_name,
            "response_format": "mp3",
            "speed": speed,
        }

        t0 = time.perf_counter()
        try:
            res = await self._client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.error("OpenAI TTS synthesis error: %s", exc)
            raise

        if res.status_code != 200:
            logger.error("OpenAI TTS error: %s - %s", res.status_code, res.text)
            raise RuntimeError(f"OpenAI TTS synthesis failed: {res.status_code}")

        audio_data = res.content
        latency_ms = (time.perf_counter() - t0) * 1000

        return TTSResult(
            audio_data=audio_data,
            format="mp3",
            sample_rate=24000,
            duration_seconds=len(text) * 0.05,
            voice=voice or "alloy",
            language="en",
            metadata={"latency_ms": latency_ms, "provider": "openai"},
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
        """OpenAI TTS doesn't support native streaming; chunk the result."""
        result = await self.synthesize(text, voice=voice, language=language, speed=speed, pitch=pitch, volume=volume)
        
        chunk_size = 4096
        audio_data = result.audio_data
        
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await asyncio.sleep(0.01)
            is_final = (i + chunk_size) >= len(audio_data)
            yield StreamingTTSResult(
                audio_chunk=chunk,
                is_final=is_final,
                format="mp3",
                sample_rate=24000,
            )

    async def close(self) -> None:
        await self._client.aclose()


class GoogleCloudTTSProvider(TTSProviderBase):
    """Google Cloud Text-to-Speech provider."""

    def __init__(self, config: TTSProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                "streaming",
                "batch",
                "multilingual",
                "speed_control",
                "pitch_control",
                "volume_control",
                "ssml_support",
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh", "ar", "ru"]
        if config.supported_voices is None:
            config.supported_voices = [
                "en-US-Standard-A", "en-US-Standard-B", "en-US-Standard-C", "en-US-Standard-D", "en-US-Standard-E",
                "en-US-Wavenet-A", "en-US-Wavenet-B", "en-US-Wavenet-C", "en-US-Wavenet-D", "en-US-Wavenet-E", "en-US-Wavenet-F",
                "en-US-Neural2-A", "en-US-Neural2-B", "en-US-Neural2-C", "en-US-Neural2-D", "en-US-Neural2-E", "en-US-Neural2-F",
            ]
        super().__init__(config)

        self._credentials_path = config.extra.get("credentials_path")
        self._voice_name = config.extra.get("voice_name", "en-US-Neural2-A")
        self._language_code = config.extra.get("language_code", "en-US")

        # Initialize Google Cloud client lazily
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import texttospeech
            if self._credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials_path
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    async def health_check(self) -> bool:
        try:
            self._get_client()
            self._healthy = True
            return True
        except Exception as exc:
            logger.warning("Google Cloud TTS health check failed: %s", exc)
            self.mark_unhealthy()
            return False

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
        from google.cloud import texttospeech

        client = self._get_client()
        voice_name = voice or self._voice_name
        language_code = language or self._language_code

        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice_params = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speed,
            pitch=pitch,
            volume_gain_db=20 * (volume - 1) if volume != 1.0 else 0.0,
        )

        t0 = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                client.synthesize_speech,
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )
        except Exception as exc:
            logger.error("Google Cloud TTS synthesis error: %s", exc)
            raise

        latency_ms = (time.perf_counter() - t0) * 1000

        return TTSResult(
            audio_data=response.audio_content,
            format="mp3",
            sample_rate=24000,
            duration_seconds=len(text) * 0.05,
            voice=voice or self._voice_name,
            language=language or "en-US",
            metadata={"latency_ms": latency_ms, "provider": "google_cloud"},
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
        """Google Cloud TTS streaming via gRPC."""
        from google.cloud import texttospeech

        client = self._get_client()
        voice_name = voice or self._voice_name
        language_code = language or self._language_code

        # Use streaming synthesis
        streaming_config = texttospeech.StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name,
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
            ),
        )

        def request_generator():
            yield texttospeech.StreamingSynthesizeRequest(
                streaming_config=streaming_config,
                input=texttospeech.StreamingSynthesisInput(text=text),
            )

        try:
            responses = client.streaming_synthesize(request_generator())
            for response in responses:
                if response.audio_content:
                    yield StreamingTTSResult(
                        audio_chunk=response.audio_content,
                        is_final=False,
                        format="mp3",
                        sample_rate=24000,
                    )
        except Exception as exc:
            logger.error("Google Cloud TTS streaming error: %s", exc)
            raise

    async def close(self) -> None:
        pass


class AzureTTSProvider(TTSProviderBase):
    """Microsoft Azure Cognitive Services TTS provider."""

    def __init__(self, config: TTSProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                "streaming",
                "batch",
                "multilingual",
                "ssml_support",
                "speed_control",
                "pitch_control",
                "emotion_control",
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh"]
        if config.supported_voices is None:
            config.supported_voices = [
                "en-US-AriaNeural", "en-US-JennyNeural", "en-US-GuyNeural", "en-US-DavisNeural",
                "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
            ]
        super().__init__(config)

        self._api_key = config.api_key or getattr(settings, "AZURE_TTS_API_KEY", None)
        self._region = config.extra.get("region", "eastus")
        self._voice_name = config.extra.get("voice_name", "en-US-AriaNeural")
        
        if not self._api_key:
            logger.warning("Azure TTS API key not configured")

        base_url = f"https://{self._region}.tts.speech.microsoft.com"
        self._base_url = base_url
        self._timeout = config.timeout_seconds

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            headers={
                "Ocp-Apim-Subscription-Key": self._api_key,
                "Content-Type": "application/ssml+xml",
            } if self._api_key else {},
        )

    async def health_check(self) -> bool:
        if not self._api_key:
            self.mark_unhealthy()
            return False
        try:
            res = await self._client.get("/cognitiveservices/voices/list", timeout=5.0)
            healthy = res.status_code == 200
            self._healthy = healthy
            return healthy
        except Exception as exc:
            logger.warning("Azure TTS health check failed: %s", exc)
            self.mark_unhealthy()
            return False

    def _build_ssml(self, text: str, voice: str, speed: float, pitch: float, volume: float) -> str:
        rate = f"{int((speed - 1.0) * 100):+d}%"
        pitch_val = f"{int((pitch - 1.0) * 50):+d}%"
        volume_val = f"{int((volume - 1.0) * 100):+d}%"
        return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
            <voice name="{voice}">
                <prosody rate="{rate}" pitch="{pitch_val}" volume="{volume_val}">
                    {text}
                </prosody>
            </voice>
        </speak>"""

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
        if not self._api_key:
            raise RuntimeError("Azure TTS API key not configured")

        voice_name = voice or self._voice_name
        ssml = self._build_ssml(text, voice_name, speed, pitch, volume)

        t0 = time.perf_counter()
        try:
            res = await self._client.post(
                "/cognitiveservices/v1",
                content=ssml,
                headers={
                    "Ocp-Apim-Subscription-Key": self._api_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                },
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.error("Azure TTS synthesis error: %s", exc)
            raise

        if res.status_code != 200:
            logger.error("Azure TTS error: %s - %s", res.status_code, res.text)
            raise RuntimeError(f"Azure TTS synthesis failed: {res.status_code}")

        latency_ms = (time.perf_counter() - t0) * 1000

        return TTSResult(
            audio_data=res.content,
            format="mp3",
            sample_rate=24000,
            duration_seconds=len(text) * 0.05,
            voice=voice or self._voice_name,
            language=language or "en-US",
            metadata={"latency_ms": latency_ms, "provider": "azure"},
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
        """Azure TTS streaming - chunk the batch result."""
        result = await self.synthesize(text, voice=voice, language=language, speed=speed, pitch=pitch, volume=volume)
        
        chunk_size = 4096
        audio_data = result.audio_data
        
        for i in range(0, len(audio_data), 4096):
            chunk = audio_data[i:i + 4096]
            await asyncio.sleep(0.01)
            is_final = (i + 4096) >= len(audio_data)
            yield StreamingTTSResult(
                audio_chunk=chunk,
                is_final=is_final,
                format="mp3",
                sample_rate=24000,
            )

    async def close(self) -> None:
        await self._client.aclose()


class CoquiTTSProvider(TTSProviderBase):
    """Coqui TTS (local, open-source) provider."""

    def __init__(self, config: TTSProviderConfig) -> None:
        if not config.capabilities:
            config.capabilities = {
                "batch",
                "multilingual",
                "voice_cloning",
            }
        if config.supported_languages is None:
            config.supported_languages = ["en", "es", "fr", "de", "pt", "it", "pl", "ru", "nl", "zh", "ja"]
        if config.supported_voices is None:
            config.supported_voices = ["default", "cloned"]
        super().__init__(config)

        self._model_name = config.extra.get("model_name", "tts_models/multilingual/multi-dataset/xtts_v2")
        self._speaker_wav = config.extra.get("speaker_wav")
        self._language = config.extra.get("language", "en")
        
        # Initialize model lazily
        self._model = None

    def _get_model(self):
        if self._model is None:
            from TTS.api import TTS
            self._model = TTS(self._model_name)
        return self._model

    async def health_check(self) -> bool:
        try:
            self._get_model()
            self._healthy = True
            return True
        except Exception as exc:
            logger.warning("Coqui TTS health check failed: %s", exc)
            self.mark_unhealthy()
            return False

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
        model = self._get_model()
        lang = language or self._language
        speaker = self._speaker_wav

        t0 = time.perf_counter()
        try:
            # Coqui TTS is synchronous, run in thread pool
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = tmp.name
            
            await asyncio.to_thread(
                model.tts_to_file,
                text=text,
                file_path=temp_path,
                speaker_wav=speaker,
                language=lang,
                speed=speed,
            )
            
            # Read the generated audio
            with open(temp_path, "rb") as f:
                audio_data = f.read()
            
            # Clean up temp file
            import os
            os.unlink(temp_path)
            
        except Exception as exc:
            logger.error("Coqui TTS synthesis error: %s", exc)
            raise

        latency_ms = (time.perf_counter() - t0) * 1000

        return TTSResult(
            audio_data=audio_data,
            format="wav",
            sample_rate=22050,
            duration_seconds=len(text) * 0.05,
            voice=voice or "cloned" if speaker else "default",
            language=language or self._language,
            metadata={"latency_ms": latency_ms, "provider": "coqui"},
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
        """Coqui TTS doesn't support native streaming; chunk the result."""
        result = await self.synthesize(text, voice=voice, language=language, speed=speed, pitch=pitch, volume=volume)
        
        chunk_size = 4096
        audio_data = result.audio_data
        
        for i in range(0, len(audio_data), 4096):
            chunk = audio_data[i:i + 4096]
            await asyncio.sleep(0.01)
            is_final = (i + 4096) >= len(audio_data)
            yield StreamingTTSResult(
                audio_chunk=chunk,
                is_final=is_final,
                format="wav",
                sample_rate=22050,
            )

    async def close(self) -> None:
        pass


# Provider registry
_TTS_PROVIDERS: dict[str, TTSProviderBase] = {}


def get_tts_provider(name: str = "elevenlabs") -> TTSProviderBase:
    """Get or create a TTS provider instance."""
    global _TTS_PROVIDERS

    if name in _TTS_PROVIDERS:
        return _TTS_PROVIDERS[name]

    provider = _create_tts_provider(name)
    _TTS_PROVIDERS[name] = provider
    return provider


def _create_tts_provider(name: str) -> TTSProviderBase:
    """Create a TTS provider instance by name."""
    name = name.lower()

    if name == "mock":
        config = TTSProviderConfig(
            name="mock",
            base_url="",
            supported_languages=["en", "hi"],
            supported_voices=["default"],
            capabilities={"streaming", "batch"},
            audio_format="wav",
        )
        return MockTTSProvider(config)

    elif name == "elevenlabs":
        config = TTSProviderConfig(
            name="elevenlabs",
            base_url="https://api.elevenlabs.io",
            api_key=getattr(settings, "ELEVENLABS_API_KEY", None),
            default_voice="21m00Tcm4TlvDq8ikWAM",
            default_language="en",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "nl", "pl", "ru", "ja", "ko", "zh"],
            supported_voices=[
                "rachel", "domi", "bella", "antoni", "elli", "josh",
                "arnold", "adam", "sam", "charlie", "emily", "grace"
            ],
            capabilities={
                "streaming", "batch", "multilingual",
                "voice_cloning", "speed_control", "pitch_control",
            },
            extra={
                "model": getattr(settings, "ELEVENLABS_MODEL", "eleven_multilingual_v2"),
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
            },
            timeout_seconds=30.0,
        )
        return ElevenLabsTTSProvider(config)

    elif name == "openai":
        config = TTSProviderConfig(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key=getattr(settings, "OPENAI_API_KEY", None),
            default_voice="alloy",
            default_language="en",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh"],
            supported_voices=["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
            capabilities={
                "batch", "multilingual", "speed_control",
            },
            extra={
                "model": getattr(settings, "OPENAI_TTS_MODEL", "tts-1"),
                "voice": "alloy",
            },
            timeout_seconds=30.0,
        )
        return OpenAITTSProvider(config)

    elif name == "google_cloud":
        config = TTSProviderConfig(
            name="google_cloud",
            base_url="",
            api_key=None,
            default_voice="en-US-Neural2-A",
            default_language="en-US",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh", "ar", "ru"],
            supported_voices=[
                "en-US-Standard-A", "en-US-Standard-B", "en-US-Standard-C", "en-US-Standard-D", "en-US-Standard-E",
                "en-US-Wavenet-A", "en-US-Wavenet-B", "en-US-Wavenet-C", "en-US-Wavenet-D", "en-US-Wavenet-E", "en-US-Wavenet-F",
                "en-US-Neural2-A", "en-US-Neural2-B", "en-US-Neural2-C", "en-US-Neural2-D", "en-US-Neural2-E", "en-US-Neural2-F",
            ],
            capabilities={
                "streaming", "batch", "multilingual",
                "speed_control", "pitch_control", "volume_control", "ssml_support",
            },
            extra={
                "credentials_path": getattr(settings, "GOOGLE_CLOUD_CREDENTIALS_PATH", None),
                "project_id": getattr(settings, "GOOGLE_CLOUD_PROJECT_ID", None),
                "voice_name": "en-US-Neural2-A",
                "language_code": "en-US",
            },
            timeout_seconds=60.0,
        )
        return GoogleCloudTTSProvider(config)

    elif name == "azure":
        config = TTSProviderConfig(
            name="azure",
            base_url="",
            api_key=getattr(settings, "AZURE_TTS_API_KEY", None),
            default_voice="en-US-AriaNeural",
            default_language="en-US",
            supported_languages=["en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh"],
            supported_voices=[
                "en-US-AriaNeural", "en-US-JennyNeural", "en-US-GuyNeural", "en-US-DavisNeural",
                "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
            ],
            capabilities={
                "streaming", "batch", "multilingual",
                "ssml_support", "speed_control", "pitch_control", "emotion_control",
            },
            extra={
                "region": getattr(settings, "AZURE_TTS_REGION", "eastus"),
                "voice_name": "en-US-AriaNeural",
            },
            timeout_seconds=30.0,
        )
        return AzureTTSProvider(config)

    elif name == "coqui":
        config = TTSProviderConfig(
            name="coqui",
            base_url="",
            api_key=None,
            default_voice="default",
            default_language="en",
            supported_languages=["en", "es", "fr", "de", "pt", "it", "pl", "ru", "nl", "zh", "ja"],
            supported_voices=["default", "cloned"],
            capabilities={
                "batch", "multilingual", "voice_cloning",
            },
            extra={
                "model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
                "speaker_wav": None,
                "language": "en",
            },
            timeout_seconds=120.0,
        )
        return CoquiTTSProvider(config)

    else:
        logger.warning("Unknown TTS provider '%s', falling back to mock", name)
        return _create_tts_provider("mock")


def get_available_tts_providers() -> list[str]:
    """Get list of available TTS provider names."""
    return ["mock", "elevenlabs", "openai", "google_cloud", "azure", "coqui"]


async def get_tts_router() -> TTSProviderBase:
    """Get the default TTS provider (first available)."""
    for name in ["elevenlabs", "openai", "google_cloud", "azure", "coqui", "mock"]:
        try:
            provider = get_tts_provider(name)
            if await provider.health_check():
                return provider
        except Exception:
            continue
    # Fallback to mock
    return get_tts_provider("mock")