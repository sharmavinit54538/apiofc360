"""FastAPI endpoint for POST /api/generate using local Ollama ONLY."""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.llm.providers.registry import get_provider_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Ollama Generation"])


class GenerateRequest(BaseModel):
    model: Optional[str] = Field(
        default=None,
        description="Ollama model name (defaults to OLLAMA_MODEL or llama3.1)",
    )
    prompt: str = Field(..., description="Prompt text for text generation")
    stream: bool = Field(default=False, description="Stream output tokens if True")
    system: Optional[str] = Field(default=None, description="Optional system prompt")
    temperature: float = Field(default=0.3, description="Sampling temperature")


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    summary="Generate text via Ollama",
)
@router.post(
    "/v1/generate",
    status_code=status.HTTP_200_OK,
    summary="Generate text via Ollama (v1 prefix)",
)
async def generate_text(payload: GenerateRequest):
    """Generate completion using Ollama local AI server.

    If Ollama is unavailable, returns HTTP 503 Service Unavailable with:
    {"detail": "Ollama server is not running."}
    """
    registry = get_provider_registry()
    ollama_provider = registry.get("ollama")

    if not ollama_provider:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Ollama server is not running."},
        )

    model_name = payload.model or getattr(settings, "OLLAMA_MODEL", getattr(settings, "OLLAMA_DEFAULT_MODEL", "llama3.1"))

    # Streaming mode
    if payload.stream:
        async def text_stream() -> AsyncGenerator[bytes, None]:
            try:
                if hasattr(ollama_provider, "stream_generate"):
                    async for token in ollama_provider.stream_generate(
                        prompt=payload.prompt,
                        system=payload.system,
                        model=model_name,
                        temperature=payload.temperature,
                    ):
                        yield token.encode("utf-8")
                else:
                    messages = []
                    if payload.system:
                        messages.append({"role": "system", "content": payload.system})
                    messages.append({"role": "user", "content": payload.prompt})
                    async for token in ollama_provider.stream_chat(
                        messages=messages,
                        model=model_name,
                        temperature=payload.temperature,
                    ):
                        yield token.encode("utf-8")
            except HTTPException as exc:
                detail_msg = exc.detail if isinstance(exc.detail, str) else "Ollama server is not running."
                yield f"ERROR: {detail_msg}".encode("utf-8")
            except Exception as exc:
                logger.error("Error in streaming response: %s", exc)
                yield b"ERROR: Ollama server is not running."

        return StreamingResponse(text_stream(), media_type="text/plain")

    # Non-streaming mode: Return ONLY generated text (no JSON metadata, no markdown wrapper)
    try:
        if hasattr(ollama_provider, "complete"):
            res = await ollama_provider.complete(
                prompt=payload.prompt,
                system=payload.system,
                model=model_name,
                temperature=payload.temperature,
            )
            text_content = res.content
        else:
            messages = []
            if payload.system:
                messages.append({"role": "system", "content": payload.system})
            messages.append({"role": "user", "content": payload.prompt})
            res = await ollama_provider.chat(
                messages=messages,
                model=model_name,
                temperature=payload.temperature,
            )
            text_content = res.content

        return Response(content=text_content, media_type="text/plain")

    except HTTPException as exc:
        status_code = exc.status_code
        detail_msg = exc.detail if isinstance(exc.detail, str) else "Ollama server is not running."
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail_msg},
        )
    except Exception as exc:
        logger.error("Ollama generate endpoint exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Ollama server is not running."},
        )
