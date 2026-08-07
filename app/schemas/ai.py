"""Pydantic schemas for the AI Chat Assistant."""

from datetime import datetime
import uuid
from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    """Payload for submitting a chat message to the assistant."""

    message: str = Field(..., max_length=5000, description="The user's query.")
    conversation_id: uuid.UUID | None = Field(
        None,
        description="Optional conversation ID to continue an existing chat.",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_message_from_query(cls, values: Any) -> Any:
        if isinstance(values, dict) and "message" not in values and "query" in values:
            values["message"] = values["query"]
        return values

    @field_validator("message")
    @classmethod
    def validate_and_sanitize_message(cls, v: str) -> str:
        """Trim whitespace and reject empty messages."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty or only whitespace")
        return cleaned


class ChatResponse(BaseModel):
    """Response returned after processing a user message."""

    success: bool = True
    conversation_id: uuid.UUID
    response: str
    sources: list[str] = []
    suggestions: list[str] = []


class ConversationSummary(BaseModel):
    """Summary of a past chat conversation."""

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Individual chat message details."""

    id: uuid.UUID
    role: str  # 'user' or 'ai'
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    """Detailed conversation logs including all messages."""

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}


class RenameRequest(BaseModel):
    """Payload to rename an existing conversation."""

    title: str = Field(..., max_length=255, description="New conversation title.")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """Ensure title is not empty after stripping."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Title cannot be empty or only whitespace")
        return cleaned
