"""Pydantic schemas for AI Chat Assistant (Aurix AI Copilot) module APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SourceCitation(BaseModel):
    """Citation source for RAG knowledge answers."""

    document: str = Field("Employee Handbook 2026", description="Title of document")
    section: str = Field("Section 4.2 — Overtime & Compensation", description="Section header")
    page: Optional[int] = Field(12, description="Page number")
    similarity: float = Field(0.92, description="Vector similarity score 0-1")

    model_config = ConfigDict(from_attributes=True)


class ChartData(BaseModel):
    """Interactive chart payload."""

    title: str = Field("Overtime Hours by Department", description="Chart title")
    chart_type: str = Field("bar", description="bar | line | pie | donut")
    data: list[dict[str, Any]] = Field(default_factory=list, description="Chart dataset")

    model_config = ConfigDict(from_attributes=True)


class TableData(BaseModel):
    """Tabular data payload."""

    title: str = Field("High Risk Employees List", description="Table title")
    headers: list[str] = Field(default_factory=list, description="Column headers")
    rows: list[list[Any]] = Field(default_factory=list, description="Data rows")

    model_config = ConfigDict(from_attributes=True)


class ChatAssistantRequest(BaseModel):
    """Payload for natural language chat queries supporting message and query key aliases."""

    query: Optional[str] = Field(None, description="User prompt or question")
    message: Optional[str] = Field(None, description="User message text")
    conversation_id: Optional[str] = Field(None, description="Existing conversation UUID")
    department_id: Optional[uuid.UUID] = Field(None, description="Filter by department")
    date_range: Optional[str] = Field(None, description="Date filter e.g. 2026-07-01 to 2026-07-24")
    role: Optional[str] = Field(None, description="User role context")
    project_id: Optional[uuid.UUID] = Field(None, description="Filter by project")


class ChatAssistantResponse(BaseModel):
    """Response payload matching frontend chat requirements."""

    answer: str = Field(..., description="AI generated answer in markdown format")
    confidence: float = Field(0.97, description="Confidence score 0-1")
    sources: list[SourceCitation] = Field(default_factory=list, description="Source document citations")
    charts: list[ChartData] = Field(default_factory=list, description="Chart visual objects")
    tables: list[TableData] = Field(default_factory=list, description="Tabular data objects")
    followUpQuestions: list[str] = Field(default_factory=list, description="CamelCase follow-up questions")
    follow_up_questions: list[str] = Field(default_factory=list, description="Snake_case follow-up questions")
    conversationId: str = Field(..., description="CamelCase conversation UUID")
    conversation_id: str = Field(..., description="Snake_case conversation UUID")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReportGeneratePayload(BaseModel):
    """Payload for HR Report Generation."""

    report_type: str = Field("ATTENDANCE", description="ATTENDANCE | PAYROLL | LEAVE | PERFORMANCE | RECRUITMENT | COMPLIANCE")
    department_id: Optional[uuid.UUID] = None
    date_range: Optional[str] = "2026-07-01 to 2026-07-24"


class AnalyticsQueryPayload(BaseModel):
    """Payload for Workforce Analytics query."""

    metric_type: str = Field("HEADCOUNT", description="HEADCOUNT | ATTRITION | HIRING | PRODUCTIVITY | UTILIZATION | OVERTIME")
    department_id: Optional[uuid.UUID] = None


class RecommendationsPayload(BaseModel):
    """Payload for AI Recommendations engine."""

    domain: str = Field("RETENTION", description="PROMOTION | RETENTION | HIRING | TRAINING | COST_OPTIMIZATION")
    department_id: Optional[uuid.UUID] = None


class ChatSuggestionsResponse(BaseModel):
    """Suggested prompts for frontend copilot."""

    suggested_prompts: list[str] = Field(default_factory=list)
    popular_queries: list[str] = Field(default_factory=list)
    role_based_prompts: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ConversationHistoryItem(BaseModel):
    """Conversation history summary item."""

    conversation_id: str
    title: str
    last_message: str
    message_count: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryResponse(BaseModel):
    """List of past chat conversations."""

    total_conversations: int
    history: list[ConversationHistoryItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ChatFeedbackRequest(BaseModel):
    """User feedback payload for chat response."""

    conversation_id: str
    rating: int = Field(5, description="1 to 5 stars")
    feedback: Optional[str] = Field(None, description="Optional text feedback")
