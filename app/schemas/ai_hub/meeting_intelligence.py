"""Schemas for AI Hub Meeting Intelligence module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class MeetingIntelligenceOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalMeetingsAnalyzed: int
    totalActionItems: int
    pendingActionItems: int
    averageParticipationPct: float
    sentimentOverview: str = "POSITIVE"
    recentMeetingsCount: int


class ActionItemDto(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    task: str
    owner: str
    dueDate: Optional[str] = None
    priority: str = "MEDIUM"
    status: str = "PENDING"
    department: Optional[str] = None


class ActionItemsPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ActionItemDto]
    total: int
    page: int
    limit: int
    pages: int


class AnalyzeMeetingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    meetingId: Optional[str] = None
    transcript: str
    audioUrl: Optional[str] = None
    participants: list[str] = Field(default_factory=list)


class AnalyzeMeetingResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    meetingId: str
    summary: str
    keyDecisions: list[str] = Field(default_factory=list)
    actionItems: list[ActionItemDto] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    sentiment: str = "POSITIVE"
    engagementScore: float = 88.0
    participantsCount: int = 0


class SummarizeMeetingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    meetingId: Optional[str] = None
    transcript: str
    keyPointsCount: int = 5


class SummarizeMeetingResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    meetingId: str
    title: str
    executiveSummary: str
    keyPoints: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    nextSteps: list[str] = Field(default_factory=list)
