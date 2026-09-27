"""Schemas for AI Hub Agents module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentRegistryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agentId: str
    name: str
    description: str
    category: str
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)


class AgentRunSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    runId: str
    agentId: str
    trigger: str
    status: str
    startedAt: str
    completedAt: Optional[str] = None
    durationSeconds: Optional[float] = None
    error: Optional[str] = None


class AgentDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent: AgentRegistryItem
    lastRun: Optional[AgentRunSummary] = None
    totalRuns: int = 0
    successRate: float = 100.0


class RunAgentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    trigger: str = "manual"
    prompt: Optional[str] = None


class AgentRunResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    runId: str
    agentId: str
    status: str
    trigger: str
    prompt: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    startedAt: str
    completedAt: Optional[str] = None


class AgentHistoryPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AgentRunResult]
    total: int
    page: int
    limit: int
    pages: int


class AgentStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agentId: str
    status: str  # idle, running, error
    lastRunStatus: Optional[str] = None
    lastRunAt: Optional[str] = None
    activeRunsCount: int = 0


class AgentFeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    runId: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class AgentFeedbackResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    feedbackId: str
    runId: str
    rating: int
    comment: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    createdAt: str
