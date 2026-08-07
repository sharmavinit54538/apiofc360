"""Pydantic schemas for AI Policy Assistant module APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SourceItem(BaseModel):
    """Citation source reference for AI policy answers."""

    document: str = Field(..., description="Document title e.g. Employee Handbook.pdf")
    section: str = Field("4.2 Policy Rules", description="Policy section heading")
    page: int = Field(1, description="Page number")
    similarity: float = Field(0.92, description="Vector cosine similarity score")

    model_config = ConfigDict(from_attributes=True)


class PolicyChatRequest(BaseModel):
    """Request payload to ask the AI Policy Assistant a question."""

    query: str = Field(..., min_length=2, description="User question e.g. What is the casual leave policy?")
    conversation_id: Optional[str] = Field(None, description="Optional conversation UUID string")
    language: Optional[str] = Field("English", description="Response language")
    company_id: Optional[uuid.UUID] = Field(None, description="Company context UUID")
    department_id: Optional[uuid.UUID] = Field(None, description="Department context UUID")
    role: Optional[str] = Field(None, description="User role filter")


class PolicyChatResponse(BaseModel):
    """RAG Policy Assistant Chat response supporting dual camelCase and snake_case."""

    answer: str = Field(..., description="Synthesized AI policy answer with citations")
    confidence: float = Field(0.96, ge=0.0, le=1.0, description="RAG confidence score")
    sources: list[SourceItem] = Field(default_factory=list, description="Citation sources")

    # camelCase properties for queryPolicyAssistant frontend thunk compatibility
    conversationId: str = Field(..., description="Unique conversation session ID")
    followUpQuestions: list[str] = Field(default_factory=list, description="Suggested follow-up questions")
    relatedPolicies: list[str] = Field(default_factory=list, description="Related HR policy manuals")

    # snake_case properties
    conversation_id: str = Field(..., description="Unique conversation session ID")
    follow_up_questions: list[str] = Field(default_factory=list, description="Suggested follow-up questions")
    related_policies: list[str] = Field(default_factory=list, description="Related HR policy manuals")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PolicySearchRequest(BaseModel):
    """Payload to search company HR policies semantically."""

    query: str = Field(..., min_length=2, description="Search query string")
    document_type: Optional[str] = Field(None, description="LEAVE | TRAVEL | IT | SECURITY | PAYROLL | COMPLIANCE")
    category: Optional[str] = Field(None, description="Category filter")
    top_k: int = Field(5, ge=1, le=20, description="Top K matches to return")


class PolicySearchMatchItem(BaseModel):
    """Match item in semantic policy search."""

    document_id: uuid.UUID
    document_title: str
    category: str
    section: str
    content_chunk: str
    similarity_score: float

    model_config = ConfigDict(from_attributes=True)


class PolicySearchResponse(BaseModel):
    """Response payload for HR Policy Search."""

    query: str
    total_matches: int
    matches: list[PolicySearchMatchItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PolicySuggestionsResponse(BaseModel):
    """Suggested policy questions for employee UI."""

    frequently_asked: list[str] = Field(default_factory=list)
    popular: list[str] = Field(default_factory=list)
    recently_asked: list[str] = Field(default_factory=list)
    role_based: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PolicyHistoryItem(BaseModel):
    """Single question-answer record in conversation history."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    question: str
    answer: str
    timestamp: datetime = Field(default_factory=datetime.now)
    confidence: float = 0.95
    sources: list[SourceItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PolicyHistoryResponse(BaseModel):
    """List of past policy chat conversations."""

    total_conversations: int
    history: list[PolicyHistoryItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PolicyDocumentItem(BaseModel):
    """Summary of indexed company policy document."""

    document_id: uuid.UUID
    title: str
    category: str
    snippet: str
    created_at: datetime
    chunks_count: int = 1

    model_config = ConfigDict(from_attributes=True)


class PolicyDocumentsResponse(BaseModel):
    """List of available company policy documents."""

    total_documents: int
    documents: list[PolicyDocumentItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PolicyFeedbackRequest(BaseModel):
    """Payload to rate or provide feedback on AI policy answers."""

    conversation_id: str
    rating: int = Field(..., ge=1, le=5, description="Star rating 1 to 5")
    feedback_text: Optional[str] = Field(None, description="Optional feedback comments")


class PolicyFeedbackResponse(BaseModel):
    """Feedback submission acknowledgment."""

    message: str = "Thank you for your feedback!"
    conversation_id: str
    rating: int

    model_config = ConfigDict(from_attributes=True)
