"""Pydantic schemas for Intelligence & AI Models API."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class IntelligenceModelInfo(BaseModel):
    """Schema representing an available Intelligence/AI Model."""
    id: str = Field(..., description="Unique model identifier, e.g. llama3.1, nomic-embed-text")
    name: str = Field(..., description="Human-readable model name")
    model: str = Field(..., description="Model identifier used for LLM routing")
    provider: str = Field("ollama", description="LLM provider name, e.g. ollama")
    category: str = Field("llm", description="Model category: llm, embedding, vision, code")
    description: str = Field("", description="Detailed description of model capabilities and use cases")
    is_default: bool = Field(False, description="Whether this is the system default model for its category")
    status: str = Field("ready", description="Model operational status: ready, installed, available")
    capabilities: List[str] = Field(default_factory=list, description="List of supported capabilities")
    context_length: Optional[int] = Field(None, description="Max context length tokens")


class IntelligenceModelsResponse(BaseModel):
    """List of available intelligence models with active provider info."""
    models: List[IntelligenceModelInfo]
    default_chat_model: str
    default_embedding_model: str
    provider: str = "ollama"
    healthy: bool = True
