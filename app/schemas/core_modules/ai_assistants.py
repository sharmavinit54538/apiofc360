"""Pydantic schemas for AI Assistant Core Modules."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Shared AI Interaction Schemas ─────────────────────────────────────────────

class AIQueryRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    query: str = Field(..., description="Natural language prompt or query")
    # inferred field — confirm with product/spec owner
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional user or system context")


class AIResponse(BaseModel):
    # inferred field — confirm with product/spec owner
    id: str
    # inferred field — confirm with product/spec owner
    module: str
    # inferred field — confirm with product/spec owner
    response: str
    # inferred field — confirm with product/spec owner
    tokens_used: int = 0
    # inferred field — confirm with product/spec owner
    model: str = "gemini-1.5-pro"
    # inferred field — confirm with product/spec owner
    created_at: str


# ── Leave Assistant ────────────────────────────────────────────────────────────

class LeaveApplyNLRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    natural_language_prompt: str = Field(..., description="e.g. 'I need 2 days casual leave next week Monday and Tuesday for personal work'")
    # inferred field — confirm with product/spec owner
    leave_type: Optional[str] = None
    # inferred field — confirm with product/spec owner
    start_date: Optional[str] = None
    # inferred field — confirm with product/spec owner
    end_date: Optional[str] = None


# ── Meeting Intelligence ───────────────────────────────────────────────────────

class MeetingAnalyzeRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    transcript: str = Field(..., description="Raw meeting audio transcript or notes")
    # inferred field — confirm with product/spec owner
    title: Optional[str] = Field(None, description="Meeting subject title")
    # inferred field — confirm with product/spec owner
    participants: Optional[List[str]] = Field(default_factory=list)


# ── Performance Coach ──────────────────────────────────────────────────────────

class PerformanceChatRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    message: str = Field(..., description="Performance feedback or career goal query")
    # inferred field — confirm with product/spec owner
    focus_area: Optional[str] = Field("general", description="leadership | technical | communication | okr")
