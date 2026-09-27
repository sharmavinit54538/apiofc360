"""Schemas for AI Hub Recruiter module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecruiterOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    openJobsCount: int
    activeCandidatesCount: int
    averageMatchScore: float
    timeToHireDays: int
    offerAcceptanceRate: float
    pipelineHealth: str = "EXCELLENT"


class GenerateQuestionsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobTitle: str
    skills: list[str] = Field(default_factory=list)
    experienceLevel: str = "mid"
    category: str = "technical"


class InterviewQuestionCategory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    questions: list[str] = Field(default_factory=list)


class GenerateQuestionsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobTitle: str
    experienceLevel: str
    totalQuestions: int
    questionsByCategory: list[InterviewQuestionCategory] = Field(default_factory=list)


class MatchFilters(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    experienceMin: Optional[float] = None
    location: Optional[str] = None


class MatchCandidatesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobDescription: str
    candidateIds: list[str] = Field(default_factory=list)
    filters: MatchFilters = Field(default_factory=MatchFilters)


class MatchedCandidateItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidateId: str
    candidateName: str
    matchScore: float
    skillsScore: float
    experienceScore: float
    matchedSkills: list[str] = Field(default_factory=list)
    missingSkills: list[str] = Field(default_factory=list)
    recommendation: str  # STRONG_HIRE, HIRE, REVIEW, REJECT


class MatchCandidatesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalMatched: int
    candidates: list[MatchedCandidateItem] = Field(default_factory=list)


class ScreeningCriteria(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    experienceYears: Optional[float] = None
    requiredSkills: list[str] = Field(default_factory=list)


class ScreenResumesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobId: Optional[str] = None
    resumeUrls: list[str] = Field(default_factory=list)
    resumes: list[Any] = Field(default_factory=list)
    criteria: ScreeningCriteria = Field(default_factory=ScreeningCriteria)


class ScreenedResumeItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identifier: str
    candidateName: str
    overallScore: float
    experienceYears: float
    matchedSkills: list[str] = Field(default_factory=list)
    missingSkills: list[str] = Field(default_factory=list)
    qualificationStatus: str  # SHORTLISTED, REVIEW, REJECTED
    summary: str


class ScreenResumesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobId: Optional[str] = None
    totalScreened: int
    shortlistedCount: int
    results: list[ScreenedResumeItem] = Field(default_factory=list)
