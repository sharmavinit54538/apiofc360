"""FastAPI Router for Intelligence & AI Models endpoints (/api/v1/intelligence/*)."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, status
import httpx

from app.core.config import settings
from app.core.rbac import require_employee_or_above
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.intelligence import IntelligenceModelInfo, IntelligenceModelsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence & AI Models"])

# Canonical Supported OFC360 AI Models catalog
CANONICAL_MODELS: list[dict[str, Any]] = [
    {
        "id": "llama3.1",
        "name": "Llama 3.1 8B",
        "model": "llama3.1",
        "provider": "ollama",
        "category": "llm",
        "description": "Meta Llama 3.1 8B parameter model — primary conversational reasoning and HR decision intelligence engine.",
        "is_default": True,
        "status": "ready",
        "capabilities": ["chat", "completion", "json_mode", "streaming", "tools"],
        "context_length": 128000,
    },
    {
        "id": "llama3",
        "name": "Llama 3 8B",
        "model": "llama3",
        "provider": "ollama",
        "category": "llm",
        "description": "Meta Llama 3 8B foundational model for workforce management and qualitative evaluations.",
        "is_default": False,
        "status": "ready",
        "capabilities": ["chat", "completion", "json_mode", "streaming"],
        "context_length": 8192,
    },
    {
        "id": "nomic-embed-text",
        "name": "Nomic Embed Text",
        "model": "nomic-embed-text",
        "provider": "ollama",
        "category": "embedding",
        "description": "High-dimensional vector embedding model for resume parsing, document intelligence, and semantic skill matching.",
        "is_default": True,
        "status": "ready",
        "capabilities": ["embedding"],
        "context_length": 8192,
    },
    {
        "id": "mistral",
        "name": "Mistral 7B",
        "model": "mistral",
        "provider": "ollama",
        "category": "llm",
        "description": "Mistral 7B general reasoning, fast drafting, and workforce analytics copilot.",
        "is_default": False,
        "status": "ready",
        "capabilities": ["chat", "completion", "json_mode", "streaming"],
        "context_length": 32768,
    },
    {
        "id": "qwen2.5",
        "name": "Qwen 2.5 7B",
        "model": "qwen2.5",
        "provider": "ollama",
        "category": "llm",
        "description": "Alibaba Qwen 2.5 multilingual model with structured data synthesis and coding assessment evaluation.",
        "is_default": False,
        "status": "ready",
        "capabilities": ["chat", "completion", "json_mode", "streaming"],
        "context_length": 32768,
    },
    {
        "id": "phi3",
        "name": "Microsoft Phi-3 Mini",
        "model": "phi3",
        "provider": "ollama",
        "category": "llm",
        "description": "Ultra-lightweight, high-efficiency model for quick summarization and real-time interactive suggestions.",
        "is_default": False,
        "status": "ready",
        "capabilities": ["chat", "completion", "streaming"],
        "context_length": 4096,
    },
    {
        "id": "gemma2",
        "name": "Google Gemma 2 9B",
        "model": "gemma2",
        "provider": "ollama",
        "category": "llm",
        "description": "Google Gemma 2 9B model optimized for policy compliance auditing and enterprise document comprehension.",
        "is_default": False,
        "status": "ready",
        "capabilities": ["chat", "completion", "json_mode", "streaming"],
        "context_length": 8192,
    },
]


async def _fetch_live_installed_models() -> tuple[list[str], bool]:
    """Fetch live installed model tags from Ollama if reachable."""
    ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{ollama_url}/api/tags")
            if res.status_code == 200:
                data = res.json()
                models = [m.get("name") or m.get("model") for m in data.get("models", []) if m.get("name") or m.get("model")]
                return models, True
    except Exception as exc:
        logger.debug("Live Ollama tags query skipped: %s", exc)
    return [], False


@router.get(
    "/models",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[dict]],
    summary="List available AI & Intelligence models",
)
@router.head(
    "/models",
    status_code=status.HTTP_200_OK,
)
async def list_intelligence_models(
    claims: Annotated[Optional[dict], Depends(get_current_user_claims)] = None,
) -> APIResponse[list[dict]]:
    """Retrieve catalog of available Intelligence / AI models supported by OFC360 backend."""
    installed_tags, is_healthy = await _fetch_live_installed_models()
    
    models_result: list[dict] = []
    seen_ids = set()

    for m in CANONICAL_MODELS:
        m_copy = dict(m)
        m_id = m_copy["id"].lower()
        if installed_tags:
            is_installed = any(m_id in tag.lower() for tag in installed_tags)
            m_copy["status"] = "installed" if is_installed else "available"
        else:
            m_copy["status"] = "ready"
        models_result.append(m_copy)
        seen_ids.add(m_id)

    # If live Ollama has additional custom models installed not in canonical list, append them
    for tag in installed_tags:
        clean_tag = tag.split(":")[0].lower()
        if clean_tag not in seen_ids and tag.lower() not in seen_ids:
            is_embed = "embed" in tag.lower()
            models_result.append({
                "id": tag,
                "name": tag.title(),
                "model": tag,
                "provider": "ollama",
                "category": "embedding" if is_embed else "llm",
                "description": f"Locally deployed Ollama model {tag}",
                "is_default": False,
                "status": "installed",
                "capabilities": ["embedding"] if is_embed else ["chat", "completion", "streaming"],
                "context_length": 8192,
            })
            seen_ids.add(tag.lower())

    return APIResponse[list[dict]](
        success=True,
        message="Available intelligence models retrieved successfully.",
        data=models_result,
        errors=None,
    )
