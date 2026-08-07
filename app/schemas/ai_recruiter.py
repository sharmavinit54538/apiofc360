"""Pydantic schemas for AI Recruiter module APIs."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecruiterDashboardResponse(BaseModel):
    """Dashboard KPIs."""

    open_roles: int = Field(..., description="Number of currently active/open jobs")
    candidates_screened: int = Field(..., description="Total candidates screened / parsed")
    top_matches: int = Field(..., description="Total candidates with high match score (>=75%)")
    average_time_to_hire: float = Field(..., description="Average days from application to hire")

    model_config = ConfigDict(from_attributes=True)


class FunnelWeekItem(BaseModel):
    """Weekly candidate funnel stage metrics."""

    week: str = Field(..., description="Week label, e.g. W1, 2026-W30")
    applied: int = 0
    screened: int = 0
    shortlisted: int = 0
    interviewed: int = 0
    selected: int = 0
    rejected: int = 0
    offer_sent: int = 0
    offer_accepted: int = 0

    model_config = ConfigDict(from_attributes=True)


class MatchDistributionResponse(BaseModel):
    """JD Match distribution buckets."""

    band_90_100: int = 0
    band_80_89: int = 0
    band_70_79: int = 0
    band_60_69: int = 0
    below_60: int = 0

    model_config = ConfigDict(from_attributes=True)


class RecruitmentAnalyticsResponse(BaseModel):
    """Full recruitment analytics breakdown."""

    time_to_hire_days: float = 0.0
    time_to_fill_days: float = 0.0
    source_of_hire: list[dict[str, Any]] = Field(default_factory=list)
    department_wise_hiring: list[dict[str, Any]] = Field(default_factory=list)
    hiring_trend: list[dict[str, Any]] = Field(default_factory=list)
    offer_acceptance_rate: float = 0.0
    interview_success_rate: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class CandidateScoreResponse(BaseModel):
    """Detailed candidate multi-dimensional score."""

    candidate_id: uuid.UUID
    candidate_name: str
    overall_score: float = 0.0
    skill_score: float = 0.0
    experience_score: float = 0.0
    culture_score: float = 0.0
    communication_score: float = 0.0
    growth_score: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class HiringRecommendationResponse(BaseModel):
    """AI Hiring Recommendation for candidate."""

    candidate_id: uuid.UUID
    candidate_name: str
    recommendation: str = Field(..., description="STRONG_HIRE | HIRE | MAYBE | REJECT")
    confidence: float = Field(..., ge=0.0, le=100.0)
    reason: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    risk_analysis: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ResumeAnalyzeRequest(BaseModel):
    """Request payload for resume analysis."""

    resume_id: Optional[uuid.UUID] = None
    candidate_id: Optional[uuid.UUID] = None


class ResumeAnalyzeResponse(BaseModel):
    """Result of automated resume analysis."""

    resume_id: uuid.UUID
    candidate_id: Optional[uuid.UUID] = None
    candidate_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    experience_years: float = 0.0
    education: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    keywords_matched: list[str] = Field(default_factory=list)
    parsed_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class JDMatchRequest(BaseModel):
    """Request to match candidate against job description."""

    job_id: uuid.UUID
    candidate_id: uuid.UUID


class JDMatchResponse(BaseModel):
    """Semantic match result between candidate and JD."""

    job_id: uuid.UUID
    candidate_id: uuid.UUID
    match_score: float = Field(..., description="Match percentage (0 to 100)")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    recommendation: str = Field(..., description="SHORTLIST | REVIEW | REJECT")

    model_config = ConfigDict(from_attributes=True)


class CandidateRankRequest(BaseModel):
    """Request payload for ranking candidates for a job."""

    job_id: uuid.UUID
    candidate_ids: Optional[list[uuid.UUID]] = None


class RankedCandidateItem(BaseModel):
    """Ranked candidate entry."""

    rank: int
    candidate_id: uuid.UUID
    candidate_name: str
    total_score: float
    skill_score: float
    experience_score: float
    education_score: float
    location_score: float
    salary_score: float
    notice_period_score: float
    previous_interview_score: float

    model_config = ConfigDict(from_attributes=True)


class CandidateRankResponse(BaseModel):
    """Ranked list of candidates for a job position."""

    job_id: uuid.UUID
    total_candidates: int
    ranked_candidates: list[RankedCandidateItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class GenerateInterviewQuestionsRequest(BaseModel):
    """Request payload for generating AI interview questions."""

    job_id: uuid.UUID
    candidate_id: uuid.UUID


class GenerateInterviewQuestionsResponse(BaseModel):
    """AI Generated interview questions grouped by type."""

    job_id: uuid.UUID
    candidate_id: uuid.UUID
    technical: list[str] = Field(default_factory=list)
    behavioral: list[str] = Field(default_factory=list)
    scenario_based: list[str] = Field(default_factory=list)
    managerial: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
