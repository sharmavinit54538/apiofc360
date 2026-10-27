"""Pydantic schemas for AI Assistant Core Modules."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Shared AI Interaction Schemas ─────────────────────────────────────────────

class AIQueryRequest(BaseModel):
    """Flexible payload for AI queries with multiple field aliases."""
    query: Optional[str] = Field(None, description="Natural language prompt or question")
    message: Optional[str] = Field(None, description="User message text alias")
    content: Optional[str] = Field(None, description="User message text alias")
    prompt: Optional[str] = Field(None, description="User prompt alias")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional user or system context")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def text(self) -> str:
        return (self.query or self.message or self.content or self.prompt or "").strip()


class AIResponse(BaseModel):
    id: str
    module: str
    response: str
    content: Optional[str] = None
    reply: Optional[str] = None
    message: Optional[str] = None
    tokens_used: int = 0
    model: str = "llama3:latest"
    created_at: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.content is None:
            self.content = self.response
        if self.reply is None:
            self.reply = self.response
        if self.message is None:
            self.message = self.response


# ── Leave Assistant ────────────────────────────────────────────────────────────

class LeaveApplyNLRequest(BaseModel):
    natural_language_prompt: str = Field(..., description="e.g. 'I need 2 days casual leave next week Monday and Tuesday for personal work'")
    leave_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ── Meeting Intelligence ───────────────────────────────────────────────────────

class MeetingAnalyzeRequest(BaseModel):
    transcript: str = Field(..., description="Raw meeting audio transcript or notes")
    title: Optional[str] = Field(None, description="Meeting subject title")
    participants: Optional[List[str]] = Field(default_factory=list)


# ── Performance Coach ──────────────────────────────────────────────────────────

class PerformanceChatRequest(BaseModel):
    message: str = Field(..., description="Performance feedback or career goal query")
    focus_area: Optional[str] = Field("general", description="leadership | technical | communication | okr")
