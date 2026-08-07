"""Pydantic schemas for AI Meeting Intelligence module APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MeetingSummaryItem(BaseModel):
    """Executive summary and key insights of a meeting."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_title: str = Field("Weekly Engineering Alignment", description="Title of the meeting")
    date: str = Field("2026-07-24", description="Meeting date")
    executive_summary: str = Field("Reviewed Q3 deliverables, team workload, and technical infrastructure updates.")
    key_decisions: list[str] = Field(default_factory=list)
    important_highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ActionItem(BaseModel):
    """Extracted action item from meeting."""

    task: str = Field("Deploy updated API middleware", description="Task description")
    owner: str = Field("Vinod Member", description="Task assignee owner")
    due_date: str = Field("2026-07-28", description="Target completion date")
    priority: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    status: str = Field("PENDING", description="PENDING | IN_PROGRESS | COMPLETED")
    department: str = Field("Engineering", description="Owner department")

    model_config = ConfigDict(from_attributes=True)


class FollowUpItem(BaseModel):
    """Follow-up task tracking record."""

    task: str = Field("Review performance test results", description="Follow-up task")
    owner: str = Field("Karan Sharma", description="Follow-up owner")
    due_date: str = Field("2026-07-29", description="Due date")
    status: str = Field("PENDING", description="PENDING | COMPLETED | OVERDUE | UPCOMING")
    type: str = Field("FOLLOW_UP", description="Task type")

    model_config = ConfigDict(from_attributes=True)


class MeetingDashboardResponse(BaseModel):
    """Meeting Intelligence Dashboard KPIs supporting dual camelCase and snake_case for frontend thunk fetchMeetingIntelligence."""

    # camelCase properties for frontend thunk compatibility
    meetingsAnalyzed: int = Field(24, description="Total Meetings Analyzed")
    actionItems: int = Field(18, description="Total Action Items Extracted")
    followUps: int = Field(7, description="Open Follow-up Tasks")
    avgDuration: str = Field("45 mins", description="Average Meeting Duration")
    meetingVolume: list[dict[str, Any]] = Field(default_factory=list)
    actionItemsByWeek: list[dict[str, Any]] = Field(default_factory=list)
    summaries: list[MeetingSummaryItem] = Field(default_factory=list)
    teamInsights: dict[str, Any] = Field(default_factory=dict)
    discussionAnalytics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)

    # Standard snake_case properties
    meetings_analyzed: int = Field(24, description="Total Meetings Analyzed")
    action_items: int = Field(18, description="Total Action Items Extracted")
    follow_ups: int = Field(7, description="Open Follow-up Tasks")
    avg_duration: str = Field("45 mins", description="Average Meeting Duration")
    meeting_volume: list[dict[str, Any]] = Field(default_factory=list)
    action_items_by_week: list[dict[str, Any]] = Field(default_factory=list)
    team_insights: dict[str, Any] = Field(default_factory=dict)
    discussion_analytics: dict[str, Any] = Field(default_factory=dict)

    # Additional KPIs
    average_attendance: int = Field(6, description="Average Meeting Attendance")
    decisions_captured: int = Field(32, description="Total Decisions Captured")
    completion_rate: float = Field(88.5, description="Action Item Completion Rate %")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MeetingSummariesResponse(BaseModel):
    """List of meeting summaries."""

    total_summaries: int
    summaries: list[MeetingSummaryItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ActionItemsResponse(BaseModel):
    """List of extracted action items."""

    total_action_items: int
    action_items: list[ActionItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class FollowUpsResponse(BaseModel):
    """Follow-up task tracking metrics."""

    pending_count: int = 4
    completed_count: int = 12
    overdue_count: int = 1
    upcoming_count: int = 3
    follow_ups: list[FollowUpItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TeamInsightsResponse(BaseModel):
    """Team participation and engagement insights."""

    participation_pct: float = 91.5
    speaking_time_min: float = 38.0
    silent_participants_count: int = 1
    engagement_score: float = 88.0
    team_collaboration_score: float = 92.0
    meeting_sentiment: str = "POSITIVE"
    insights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DiscussionAnalyticsResponse(BaseModel):
    """Topics discussed and time allocation metrics."""

    topics_discussed: list[str] = Field(default_factory=list)
    topic_frequency: dict[str, int] = Field(default_factory=dict)
    time_spent_per_topic: dict[str, str] = Field(default_factory=dict)
    recurring_topics: list[str] = Field(default_factory=list)
    ai_insights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MeetingVolumeResponse(BaseModel):
    """Meeting volume distribution across time & teams."""

    daily_meetings: list[dict[str, Any]] = Field(default_factory=list)
    weekly_meetings: list[dict[str, Any]] = Field(default_factory=list)
    monthly_meetings: list[dict[str, Any]] = Field(default_factory=list)
    department_meetings: list[dict[str, Any]] = Field(default_factory=list)
    team_meetings: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MeetingDetailResponse(BaseModel):
    """Detailed view of a single analyzed meeting."""

    id: uuid.UUID
    meeting_title: str
    meeting_transcript: str
    summary: str
    action_items: list[ActionItem] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    task_assignments: list[dict[str, Any]] = Field(default_factory=list)
    mom: str
    followup_reminders: list[FollowUpItem] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Request Payloads
class AnalyzeMeetingPayload(BaseModel):
    """Payload to analyze a meeting transcript or recording."""

    meeting_id: Optional[str] = Field(None, description="Optional existing meeting ID")
    meeting_title: str = Field("Engineering Alignment Sync", description="Title of the meeting")
    transcript: str = Field(..., min_length=10, description="Meeting transcript text")
    recording_url: Optional[str] = Field(None, description="Optional audio/video recording URL")


class SummarizeMeetingPayload(BaseModel):
    """Payload to summarize meeting transcript."""

    meeting_title: str = Field("Product Strategy Meeting", description="Title")
    transcript: str = Field(..., min_length=10, description="Transcript text")


class ExtractActionItemsPayload(BaseModel):
    """Payload to extract action items."""

    transcript: str = Field(..., min_length=10, description="Transcript text")


class GenerateFollowupsPayload(BaseModel):
    """Payload to generate follow-up reminders."""

    transcript: str = Field(..., min_length=10, description="Transcript text")
