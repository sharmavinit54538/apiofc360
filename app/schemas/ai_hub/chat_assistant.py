"""Schemas for AI Hub Chat Assistant module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatMessageItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: str  # user or ai / assistant
    content: str
    createdAt: str


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    agentId: Optional[str] = None
    initialMessage: Optional[str] = None


class ChatConversationSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversationId: str
    title: str
    agentId: Optional[str] = None
    messageCount: int = 0
    lastMessage: Optional[str] = None
    createdAt: str
    updatedAt: str


class ChatConversationDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversationId: str
    title: str
    agentId: Optional[str] = None
    messages: list[ChatMessageItem] = Field(default_factory=list)
    createdAt: str
    updatedAt: str


class ChatConversationsPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ChatConversationSummary]
    total: int
    page: int
    limit: int
    pages: int


class ChatConversationDeleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversationId: str
    deleted: bool = True


class SendChatMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversationId: str
    content: str
    agentId: Optional[str] = None


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversationId: str
    messageId: str
    role: str = "ai"
    content: str
    agentId: Optional[str] = None
    suggestions: list[str] = Field(default_factory=list)
    createdAt: str
