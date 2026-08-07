"""Pydantic v2 schemas for the AI Hiring Copilot module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Extractions & Parsing Schemas
# ---------------------------------------------------------------------------

class ExtractionDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    github_url: str | None = None
    summary: str | None = None
    skills: dict | None = None
    experience: list | None = None
    education: list | None = None
    projects: list | None = None
    certifications: list | None = None


# ---------------------------------------------------------------------------
# Matching & Embedding Schemas
# ---------------------------------------------------------------------------

class SemanticMatchRequest(BaseModel):
    resume_document_id: uuid.UUID
    job_id: uuid.UUID


class SemanticMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    score: float
    matching_skills: list[str] = []
    missing_skills: list[str] = []


# ---------------------------------------------------------------------------
# Qualitative AI Analysis Schemas (Llama3 Outputs)
# ---------------------------------------------------------------------------

class AiAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    professional_summary: str
    strengths: list[str] = []
    weaknesses: list[str] = []
    risk_factors: list[str] = []
    hiring_recommendation: str
    culture_fit: str | None = None
    technical_fit: str | None = None
    communication_assessment: str | None = None
    career_progression: str | None = None
    skill_gaps: list[str] = []
    upskilling_suggestions: list[str] = []
    confidence_score: float


# ---------------------------------------------------------------------------
# Ranking Schemas
# ---------------------------------------------------------------------------

class CandidateRankingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    overall_score: float
    technical_score: float
    experience_score: float
    education_score: float
    project_score: float
    certification_score: float
    communication_score: float
    leadership_score: float
    culture_score: float
    learning_score: float


class CandidateRankListItem(BaseModel):
    resume_document_id: uuid.UUID
    candidate_name: str
    overall_score: float
    ranking_order: int


# ---------------------------------------------------------------------------
# Interview Questions Schemas
# ---------------------------------------------------------------------------

class QuestionListItem(BaseModel):
    question: str
    expected_answer: str = Field(..., alias="expected_answer")
    category: str
    difficulty: str
    checklist: list[str] = []


class InterviewQuestionsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    questions: list[QuestionListItem] = []


# ---------------------------------------------------------------------------
# Dashboard Schema
# ---------------------------------------------------------------------------

class AiCopilotDashboardView(BaseModel):
    overall_score: float
    technical_score: float
    experience_score: float
    education_score: float
    project_score: float
    communication_score: float
    leadership_score: float
    culture_score: float
    skill_match_percentage: float = Field(..., alias="skill_match_percentage")
    experience_match_percentage: float = Field(..., alias="experience_match_percentage")
    education_match_percentage: float = Field(..., alias="education_match_percentage")
    top_skills: list[str] = []
    missing_skills: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    resume_summary: str = Field(..., alias="resume_summary")
    career_timeline: list[dict] = Field(..., alias="career_timeline")
    ai_recommendation: str = Field(..., alias="ai_recommendation")
    interview_questions: list[dict] = Field(..., alias="interview_questions")
    risk_analysis: list[str] = Field(..., alias="risk_analysis")
    confidence_score: float
