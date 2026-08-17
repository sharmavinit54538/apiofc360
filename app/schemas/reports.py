"""Pydantic schemas for OFC360 Reports APIs (Engagement, Culture, Performance)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ==============================================================================
# 1. Engagement & eNPS Reports Schemas
# ==============================================================================

class EngagementSummaryData(BaseModel):
    """Aggregate company engagement metrics."""
    engagement_score: Optional[float] = Field(None, description="Calculated overall engagement score (0-100)")
    participation_rate: Optional[float] = Field(None, description="Percentage of eligible workforce who participated (%)")
    eNPS: Optional[float] = Field(None, description="Employee Net Promoter Score (-100 to 100)")
    response_rate: Optional[float] = Field(None, description="Overall survey response rate (%)")
    active_surveys: int = Field(0, description="Count of currently active/open surveys")
    completed_surveys: int = Field(0, description="Count of concluded/closed surveys")
    total_responses: int = Field(0, description="Total recorded response/vote count")
    
    # Aliases / Extended fields for frontend compatibility
    enpsScore: Optional[float] = Field(None, description="Compatibility alias for eNPS")
    promoters: Optional[float] = Field(None, description="Percentage of promoter respondents (%)")
    passives: Optional[float] = Field(None, description="Percentage of passive respondents (%)")
    detractors: Optional[float] = Field(None, description="Percentage of detractor respondents (%)")


class EngagementTrendItem(BaseModel):
    """Historical monthly engagement trend item."""
    period: str = Field(..., description="Month identifier (YYYY-MM)")
    engagement_score: Optional[float] = Field(None, description="Engagement score for the period")
    response_rate: Optional[float] = Field(None, description="Response rate for the period (%)")


class EnpsTrendItem(BaseModel):
    """Historical monthly eNPS trend item."""
    period: str = Field(..., description="Month identifier (YYYY-MM)")
    enps: Optional[float] = Field(None, description="eNPS score for the period (-100 to 100)")
    month: Optional[str] = Field(None, description="Human readable month label (e.g. Mar 2026)")
    score: Optional[float] = Field(None, description="Normalized score alias")
    responses: int = Field(0, description="Total responses in this period")


class EngagementBreakdownItem(BaseModel):
    """Engagement breakdown by organizational dimension (e.g. department)."""
    department: str = Field(..., description="Department or organizational unit name")
    engagement_score: Optional[float] = Field(None, description="Average engagement score (0-100)")
    response_rate: Optional[float] = Field(None, description="Response rate percentage (%)")
    responses: int = Field(0, description="Total recorded responses from this department")


class EngagementSurveyItem(BaseModel):
    """Individual survey summary record."""
    id: uuid.UUID = Field(..., description="Unique survey ID")
    survey_name: str = Field(..., description="Title / question of the survey")
    status: str = Field(..., description="Survey status: OPEN | CLOSED | DRAFT")
    start_date: date = Field(..., description="Start date of survey")
    end_date: Optional[date] = Field(None, description="End date of survey")
    participants: int = Field(0, description="Total eligible participants")
    responses: int = Field(0, description="Total responses received")
    response_rate: Optional[float] = Field(None, description="Response rate percentage (%)")
    score: Optional[float] = Field(None, description="Average score / rating for this survey")


class EngagementSurveyListResponse(BaseModel):
    """Paginated list of engagement surveys."""
    items: List[EngagementSurveyItem] = Field(default_factory=list)
    total: int = Field(0, description="Total number of survey records")
    page: int = Field(1, description="Current page number")
    limit: int = Field(10, description="Number of items per page")


# ==============================================================================
# 2. Culture & D&I Telemetry Reports Schemas
# ==============================================================================

class CultureDistributionItem(BaseModel):
    """Demographic or categorical distribution bucket."""
    label: str = Field(..., description="Category or demographic bucket label")
    value: float = Field(..., description="Percentage or count representation")


class CultureTelemetryData(BaseModel):
    """Organizational culture telemetry and D&I telemetry."""
    culture_score: Optional[float] = Field(None, description="Composite culture index (0-100)")
    belonging_score: Optional[float] = Field(None, description="Employee sense of belonging index (0-100)")
    manager_effectiveness: Optional[float] = Field(None, description="Manager effectiveness score (0-100)")
    collaboration_score: Optional[float] = Field(None, description="Cross-team collaboration score (0-100)")
    recognition_score: Optional[float] = Field(None, description="Employee recognition index (0-100)")
    psychological_safety: Optional[float] = Field(None, description="Psychological safety index (0-100)")
    
    # D&I Metrics
    inclusionIndex: Optional[float] = Field(None, description="Inclusion index score (0-100)")
    diHiringRatio: Optional[float] = Field(None, description="D&I hiring ratio percentage (%)")
    genderDistribution: List[CultureDistributionItem] = Field(default_factory=list, description="Gender breakdown")
    ageDistribution: List[CultureDistributionItem] = Field(default_factory=list, description="Age bracket breakdown")


class CultureTrendItem(BaseModel):
    """Historical monthly culture trend."""
    period: str = Field(..., description="Month identifier (YYYY-MM)")
    culture_score: Optional[float] = Field(None, description="Culture score for the period")
    belonging_score: Optional[float] = Field(None, description="Belonging score for the period")


class CultureBreakdownItem(BaseModel):
    """Culture breakdown by department or dimension."""
    department: str = Field(..., description="Department name")
    culture_score: Optional[float] = Field(None, description="Culture score (0-100)")
    belonging_score: Optional[float] = Field(None, description="Belonging score (0-100)")
    collaboration_score: Optional[float] = Field(None, description="Collaboration score (0-100)")
    headcount: int = Field(0, description="Active headcount in department")


class CultureFeedbackTheme(BaseModel):
    """Aggregated sanitized feedback theme."""
    theme: str = Field(..., description="Theme or topic title")
    count: int = Field(0, description="Mention count")
    sentiment_score: Optional[float] = Field(None, description="Average sentiment score (0-10)")


class CultureFeedbackData(BaseModel):
    """Aggregated and sanitized employee feedback overview."""
    total_feedback: int = Field(0, description="Total feedback records analyzed")
    positive_sentiment_pct: Optional[float] = Field(None, description="Positive sentiment percentage (%)")
    neutral_sentiment_pct: Optional[float] = Field(None, description="Neutral sentiment percentage (%)")
    negative_sentiment_pct: Optional[float] = Field(None, description="Negative sentiment percentage (%)")
    themes: List[CultureFeedbackTheme] = Field(default_factory=list, description="Categorized feedback themes")
