"""Pydantic schemas for AI Resume Screening & ATS Matching system."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class EducationEntrySchema(BaseModel):
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    university: Optional[str] = None
    college: Optional[str] = None
    passing_year: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectEntrySchema(BaseModel):
    title: str
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ExperienceEntrySchema(BaseModel):
    company: str
    designation: Optional[str] = None
    duration_months: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ParsedResumeSchema(BaseModel):
    """Extracted and normalized candidate resume details."""
    candidate_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    summary: Optional[str] = None

    total_experience_years: float = 0.0
    current_company: Optional[str] = None
    previous_companies: list[str] = Field(default_factory=list)
    current_designation: Optional[str] = None

    skills: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    education: list[EducationEntrySchema] = Field(default_factory=list)
    work_history: list[ExperienceEntrySchema] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[ProjectEntrySchema] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    internships: list[dict[str, Any]] = Field(default_factory=list)

    current_salary: Optional[float] = None
    expected_salary: Optional[float] = None
    notice_period_days: Optional[int] = None
    current_location: Optional[str] = None
    preferred_location: Optional[str] = None
    willing_to_relocate: bool = True

    model_config = ConfigDict(from_attributes=True)


class ATSScoreBreakdownSchema(BaseModel):
    """Multi-dimensional ATS compatibility score breakdown (0 - 100)."""
    overall_ats_score: float = Field(0.0, ge=0.0, le=100.0)
    skill_match_score: float = Field(0.0, ge=0.0, le=100.0)
    experience_match_score: float = Field(0.0, ge=0.0, le=100.0)
    education_match_score: float = Field(0.0, ge=0.0, le=100.0)
    keyword_match_score: float = Field(0.0, ge=0.0, le=100.0)
    role_match_score: float = Field(0.0, ge=0.0, le=100.0)
    industry_match_score: float = Field(0.0, ge=0.0, le=100.0)
    location_match_score: float = Field(0.0, ge=0.0, le=100.0)
    certification_match_score: float = Field(0.0, ge=0.0, le=100.0)
    resume_completeness: float = Field(0.0, ge=0.0, le=100.0)
    formatting_quality: float = Field(0.0, ge=0.0, le=100.0)

    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    extra_skills: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AIInsightsSchema(BaseModel):
    """AI hiring insights and interview recommendations."""
    candidate_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    recommended_interview_questions: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    hiring_recommendation: str = Field("REVIEW", description="SHORTLIST | REVIEW | REJECT")
    career_level: str = Field("Mid", description="Junior | Mid | Senior | Lead | Executive")
    technical_assessment: str = ""
    communication_assessment: str = ""
    leadership_indicators: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class QualityAnalysisSchema(BaseModel):
    """Resume quality and structural validation results."""
    is_valid: bool = True
    issues: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    formatting_score: float = 100.0
    is_readable: bool = True
    is_image_only: bool = False

    model_config = ConfigDict(from_attributes=True)


class DuplicateDetectionSchema(BaseModel):
    """Duplicate candidate detection status."""
    is_duplicate: bool = False
    duplicate_candidate_id: Optional[str] = None
    matched_by: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CandidateScreeningResponse(BaseModel):
    """Structured response for POST /api/v1/recruitment/resume/upload."""
    candidate_id: str
    application_id: Optional[str] = None
    resume_document_id: str
    job_id: Optional[str] = None
    status: str = "COMPLETED"
    ats_score: float = 0.0
    rank: int = 1
    match_tier: str = Field("Good Match", description="Best Match | Good Match | Average Match | Low Match")

    candidate_details: ParsedResumeSchema
    ats_breakdown: ATSScoreBreakdownSchema
    ai_insights: AIInsightsSchema
    quality_analysis: QualityAnalysisSchema
    duplicate_info: DuplicateDetectionSchema
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateListItemSchema(BaseModel):
    """Summary item for GET /api/v1/recruitment/candidates."""
    candidate_id: uuid.UUID
    resume_document_id: Optional[uuid.UUID] = None
    application_id: Optional[uuid.UUID] = None
    job_id: Optional[uuid.UUID] = None
    job_title: Optional[str] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    current_company: Optional[str] = None
    current_role: Optional[str] = None
    years_experience: float = 0.0
    ats_score: float = 0.0
    rank: int = 1
    match_tier: str = "Good Match"
    status: str = "PENDING"
    created_at: datetime
    applied_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CandidateProfileDetailResponse(BaseModel):
    """Detailed profile response for GET /api/v1/recruitment/candidates/{candidate_id}."""
    candidate_id: uuid.UUID
    resume_document_id: Optional[uuid.UUID] = None
    application_id: Optional[uuid.UUID] = None
    job_id: Optional[uuid.UUID] = None

    candidate_details: ParsedResumeSchema
    ats_breakdown: Optional[ATSScoreBreakdownSchema] = None
    ai_insights: Optional[AIInsightsSchema] = None
    quality_analysis: Optional[QualityAnalysisSchema] = None

    raw_text: Optional[str] = None
    resume_preview_url: Optional[str] = None
    status: str = "COMPLETED"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateATSAnalysisResponse(BaseModel):
    """Detailed ATS response for GET /api/v1/recruitment/candidates/{candidate_id}/ats."""
    candidate_id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    overall_ats_score: float
    rank: int
    match_tier: str
    ats_breakdown: ATSScoreBreakdownSchema
    ai_insights: AIInsightsSchema

    model_config = ConfigDict(from_attributes=True)


class JobMatchRequest(BaseModel):
    job_id: uuid.UUID


class JobMatchResponse(BaseModel):
    job_id: uuid.UUID
    total_candidates_matched: int
    top_matched_candidates: list[dict[str, Any]] = Field(default_factory=list)
    average_ats_score: float = 0.0
    message: str = "ATS scores recalculated and rankings updated successfully."
