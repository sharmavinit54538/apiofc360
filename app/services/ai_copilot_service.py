"""AI Hiring Copilot service layer — Orchestrates all pipeline stages using local Ollama."""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DatabaseException
from app.db.database import get_db_session
from app.repositories.ai_copilot_repository import AiCopilotRepository
from app.services.ollama_client import OllamaClient, ollama_client
from app.services.pdf_docx_parser import extract_document_text
from app.schemas.ai_copilot import (
    AiAnalysisResponse,
    AiCopilotDashboardView,
    CandidateRankingResponse,
    ExtractionDataResponse,
    InterviewQuestionsResponse,
    SemanticMatchResponse,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"}
MAX_RESUME_SIZE = 10 * 1024 * 1024  # 10 MB
UPLOAD_DIR = "uploads/resumes"


# ---------------------------------------------------------------------------
# Prompt Templates (Production grade)
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a professional HR resume parser.
Extract structured information from a resume text and return STRICTLY valid JSON with no explanation.
Return ONLY the JSON object."""

EXTRACTION_USER_TEMPLATE = """Parse this resume and extract the following JSON schema:
{{
  "name": "full name",
  "email": "email address",
  "phone": "phone number",
  "location": "city/country",
  "linkedin_url": "linkedin url or null",
  "portfolio_url": "portfolio url or null",
  "github_url": "github url or null",
  "summary": "professional summary",
  "skills": {{
    "programming_languages": [],
    "frameworks": [],
    "databases": [],
    "cloud": [],
    "tools": [],
    "other": []
  }},
  "experience": [
    {{
      "company": "company name",
      "role": "job title",
      "start_date": "start date",
      "end_date": "end date or Present",
      "description": "responsibilities"
    }}
  ],
  "education": [
    {{
      "institution": "university name",
      "degree": "degree type",
      "field": "major",
      "graduation_year": "year"
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "description": "description",
      "tech_stack": [],
      "url": "url or null"
    }}
  ],
  "certifications": ["list of certifications"],
  "achievements": ["achievements"],
  "expected_salary": "expected salary or null",
  "current_salary": "current salary or null",
  "notice_period": "notice period or null"
}}

RESUME TEXT:
{resume_text}

Return ONLY valid JSON:"""

ANALYSIS_SYSTEM_PROMPT = """You are a senior technical recruiter and hiring manager at a top tech company.
Analyze a resume against a job description and return a JSON assessment.
Be professional, specific, and data-driven. Return ONLY valid JSON."""

ANALYSIS_USER_TEMPLATE = """Analyze this candidate for the given job position.

JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}

SEMANTIC MATCH SCORE: {match_score:.2f}
MATCHING SKILLS: {matching_skills}
MISSING SKILLS: {missing_skills}

Return this exact JSON structure:
{{
  "professional_summary": "2-3 sentence professional summary of candidate",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "risk_factors": ["risk 1", "risk 2"],
  "hiring_recommendation": "Strong Hire|Hire|Maybe|Reject",
  "culture_fit": "assessment of culture fit",
  "technical_fit": "assessment of technical fit",
  "communication_assessment": "assessment of communication skills based on resume",
  "career_progression": "assessment of career trajectory",
  "skill_gaps": ["gap 1", "gap 2"],
  "upskilling_suggestions": ["suggestion 1", "suggestion 2"],
  "confidence_score": 0.85
}}

Return ONLY valid JSON:"""

INTERVIEW_SYSTEM_PROMPT = """You are an expert technical interviewer. Generate targeted interview questions
for a candidate based on their resume and the job requirements. Return ONLY valid JSON."""

INTERVIEW_USER_TEMPLATE = """Generate interview questions for this candidate applying for the position below.

JOB DESCRIPTION:
{job_description}

CANDIDATE PROFILE:
{resume_summary}

Generate exactly 15 questions across these categories: Technical (5), System Design (2), Coding (2), Behavioral (3), HR (3).
Return this exact JSON:
{{
  "questions": [
    {{
      "question": "Question text here",
      "expected_answer": "Expected answer or key points to look for",
      "category": "Technical|System Design|Coding|Behavioral|HR",
      "difficulty": "Easy|Medium|Hard",
      "checklist": ["evaluation point 1", "evaluation point 2"]
    }}
  ]
}}

Return ONLY valid JSON:"""


# ---------------------------------------------------------------------------
# Utility: Cosine Similarity
# ---------------------------------------------------------------------------

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Utility: Skill Matcher (rule-based)
# ---------------------------------------------------------------------------

def extract_skill_list(skills_dict: dict | None) -> list[str]:
    if not skills_dict:
        return []
    all_skills = []
    for category_skills in skills_dict.values():
        if isinstance(category_skills, list):
            all_skills.extend([s.lower().strip() for s in category_skills if isinstance(s, str)])
    return list(set(all_skills))


def find_matching_missing_skills(candidate_skills: list[str], jd_text: str) -> tuple[list[str], list[str]]:
    """Rule-based matching of candidate skills against job description keywords."""
    jd_lower = jd_text.lower()
    matching = [skill for skill in candidate_skills if skill in jd_lower]
    # Extract JD requirement words
    tech_keywords = [
        "python", "java", "go", "rust", "typescript", "javascript", "react", "vue", "angular",
        "django", "fastapi", "flask", "spring", "node.js", "postgresql", "mysql", "mongodb",
        "redis", "kafka", "docker", "kubernetes", "aws", "gcp", "azure", "terraform",
        "git", "linux", "machine learning", "tensorflow", "pytorch", "spark", "airflow"
    ]
    jd_keywords_found = [kw for kw in tech_keywords if kw in jd_lower]
    missing = [kw for kw in jd_keywords_found if kw not in candidate_skills]
    return matching, missing


# ---------------------------------------------------------------------------
# Utility: Scoring Engine (rule-based deterministic fallback)
# ---------------------------------------------------------------------------

def calculate_ranking_scores(
    similarity_score: float,
    extracted_data: dict,
    analysis: dict,
) -> dict[str, float]:
    """Compute multi-dimensional candidate ranking scores."""
    experience_list = extracted_data.get("experience") or []
    education_list = extracted_data.get("education") or []
    projects_list = extracted_data.get("projects") or []
    certifications_list = extracted_data.get("certifications") or []
    skills_dict = extracted_data.get("skills") or {}

    # Technical Score based on skill count
    all_skills = extract_skill_list(skills_dict)
    technical_score = min(100.0, len(all_skills) * 5.0)

    # Experience Score (1 year = 10 pts, max 100)
    experience_score = min(100.0, len(experience_list) * 20.0)

    # Education Score
    edu_scores = {"ph.d": 100, "doctoral": 100, "master": 80, "bachelor": 60, "diploma": 40}
    education_score = 40.0
    for edu in education_list:
        degree = str(edu.get("degree", "")).lower()
        for key, score in edu_scores.items():
            if key in degree:
                education_score = max(education_score, float(score))

    # Project Score
    project_score = min(100.0, len(projects_list) * 20.0)

    # Certification Score
    certification_score = min(100.0, len(certifications_list) * 15.0)

    # Communication Score — from analysis JSON
    comm_map = {"strong": 85.0, "good": 70.0, "average": 55.0, "weak": 40.0}
    communication_assessment = str(analysis.get("communication_assessment", "")).lower()
    communication_score = 60.0
    for key, val in comm_map.items():
        if key in communication_assessment:
            communication_score = val
            break

    # Leadership Score — based on experience descriptions
    leadership_score = 50.0
    for exp in experience_list:
        desc = str(exp.get("description", "")).lower()
        if any(word in desc for word in ["lead", "manage", "mentor", "direct", "oversee"]):
            leadership_score = 80.0

    # Culture Score from hiring recommendation
    rec_map = {
        "strong hire": 90.0,
        "hire": 75.0,
        "maybe": 55.0,
        "reject": 25.0,
    }
    recommendation = str(analysis.get("hiring_recommendation", "")).lower()
    culture_score = 55.0
    for key, val in rec_map.items():
        if key in recommendation:
            culture_score = val
            break

    # Learning Score based on certifications + projects growth
    learning_score = min(100.0, (len(certifications_list) * 10.0) + (len(projects_list) * 8.0))

    # Overall Score (weighted average)
    weights = {
        "technical": 0.25,
        "experience": 0.20,
        "education": 0.10,
        "project": 0.10,
        "certification": 0.05,
        "communication": 0.10,
        "leadership": 0.07,
        "culture": 0.08,
        "learning": 0.05,
    }

    overall_score = (
        technical_score * weights["technical"]
        + experience_score * weights["experience"]
        + education_score * weights["education"]
        + project_score * weights["project"]
        + certification_score * weights["certification"]
        + communication_score * weights["communication"]
        + leadership_score * weights["leadership"]
        + culture_score * weights["culture"]
        + learning_score * weights["learning"]
    )

    # Boost overall by semantic match
    overall_score = min(100.0, overall_score + (similarity_score * 15))

    return {
        "overall_score": round(overall_score, 2),
        "technical_score": round(technical_score, 2),
        "experience_score": round(experience_score, 2),
        "education_score": round(education_score, 2),
        "project_score": round(project_score, 2),
        "certification_score": round(certification_score, 2),
        "communication_score": round(communication_score, 2),
        "leadership_score": round(leadership_score, 2),
        "culture_score": round(culture_score, 2),
        "learning_score": round(learning_score, 2),
    }


# ---------------------------------------------------------------------------
# AI Copilot Service
# ---------------------------------------------------------------------------

class AiCopilotService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: AiCopilotRepository,
        ollama: OllamaClient,
    ) -> None:
        self.session = session
        self.repo = repo
        self.ollama = ollama

        os.makedirs(UPLOAD_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Stage 1: Resume Document Upload
    # ------------------------------------------------------------------

    async def upload_resume(self, application_id: uuid.UUID, file: UploadFile) -> dict:
        """Validate, save, and register resume document."""
        logger.info("upload_resume | application=%s | file=%s", application_id, file.filename)
        try:
            filename = file.filename or "resume.pdf"
            _, ext = os.path.splitext(filename.lower())
            if ext not in ALLOWED_EXTENSIONS:
                raise AppException(
                    message=f"Unsupported file format '{ext}'. Accepted: PDF, DOCX, DOC, PNG, JPG, JPEG.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            file_data = await file.read()
            file_size = len(file_data)
            await file.seek(0)
            if file_size > MAX_RESUME_SIZE:
                raise AppException(message="File exceeds 10MB limit.", status_code=status.HTTP_400_BAD_REQUEST)

            unique_filename = f"{uuid.uuid4().hex}{ext}"
            save_path = os.path.join(UPLOAD_DIR, unique_filename)
            with open(save_path, "wb") as f:
                f.write(file_data)

            doc = await self.repo.create_resume_document(
                application_id=application_id,
                file_path=save_path,
                file_name=filename,
                file_size=file_size,
            )

            await self.session.commit()
            return {
                "resume_document_id": str(doc.id),
                "file_name": filename,
                "file_size": file_size,
                "message": "Resume uploaded successfully. Use the resume_document_id for next pipeline stages.",
            }

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("upload_resume: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 2: Text Extraction + Structured Parsing
    # ------------------------------------------------------------------

    async def extract_resume(self, resume_doc_id: uuid.UUID) -> ExtractionDataResponse:
        """Extract text, parse structured JSON via local Llama3, store in DB."""
        logger.info("extract_resume | doc=%s", resume_doc_id)
        try:
            doc = await self.repo.get_resume_document_by_id(resume_doc_id)
            if not doc:
                raise AppException(message="Resume document not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check if already extracted
            existing = await self.repo.get_extracted_data(resume_doc_id)
            if existing:
                return ExtractionDataResponse.model_validate(existing.__dict__)

            t_start = time.time()
            raw_text = extract_document_text(doc.file_path)
            if not raw_text.strip():
                raise AppException(message="Could not extract text from resume document.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

            # Call local Llama3 for structured extraction
            prompt = EXTRACTION_USER_TEMPLATE.format(resume_text=raw_text[:6000])
            llm_response = await self.ollama.generate_completion(
                prompt=prompt,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                json_format=True,
            )
            duration_ms = int((time.time() - t_start) * 1000)

            # Parse LLM JSON or build basic fallback
            parsed = {}
            if llm_response:
                try:
                    parsed = json.loads(llm_response)
                except json.JSONDecodeError:
                    logger.warning("LLM returned non-JSON extraction, using raw parse fallback")
                    parsed = {}

            extracted_kwargs = {
                "resume_document_id": resume_doc_id,
                "raw_text": raw_text,
                "name": parsed.get("name"),
                "email": parsed.get("email"),
                "phone": parsed.get("phone"),
                "location": parsed.get("location"),
                "linkedin_url": parsed.get("linkedin_url"),
                "portfolio_url": parsed.get("portfolio_url"),
                "github_url": parsed.get("github_url"),
                "summary": parsed.get("summary"),
                "skills": parsed.get("skills", {}),
                "experience": parsed.get("experience", []),
                "education": parsed.get("education", []),
                "projects": parsed.get("projects", []),
                "certifications": parsed.get("certifications", []),
            }
            extracted = await self.repo.create_extracted_data(**extracted_kwargs)

            # Audit log
            await self.repo.create_ai_log(
                action="EXTRACT",
                model_used="llama3:latest",
                prompt_length=len(prompt),
                response_length=len(llm_response or ""),
                duration_ms=duration_ms,
            )

            await self.session.commit()
            return ExtractionDataResponse(**{k: v for k, v in extracted_kwargs.items() if k != "resume_document_id"})

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("extract_resume: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 3: Embedding Generation
    # ------------------------------------------------------------------

    async def generate_resume_embedding(self, resume_doc_id: uuid.UUID) -> dict:
        """Generate and store vector embedding for resume text."""
        logger.info("generate_resume_embedding | doc=%s", resume_doc_id)
        try:
            existing = await self.repo.get_resume_embedding(resume_doc_id)
            if existing:
                return {"resume_document_id": str(resume_doc_id), "message": "Embedding already generated.", "vector_dims": len(existing.vector)}

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            if not extracted:
                raise AppException(message="Resume not extracted yet. Run /extract first.", status_code=status.HTTP_400_BAD_REQUEST)

            t_start = time.time()
            text = f"{extracted.summary or ''}\n{extracted.raw_text[:3000]}"
            vector = await self.ollama.get_embedding(text)
            duration_ms = int((time.time() - t_start) * 1000)

            emb = await self.repo.create_resume_embedding(
                resume_document_id=resume_doc_id,
                vector=vector,
                model_name="nomic-embed-text:latest",
            )

            await self.repo.create_ai_log(
                action="EMBEDDING",
                model_used="nomic-embed-text:latest",
                prompt_length=len(text),
                response_length=len(vector),
                duration_ms=duration_ms,
            )

            await self.session.commit()
            return {"resume_document_id": str(resume_doc_id), "message": "Resume embedding generated successfully.", "vector_dims": len(vector)}

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("generate_resume_embedding: error", exc_info=exc)
            raise DatabaseException() from exc

    async def generate_job_embedding(self, job_id: uuid.UUID, job_description: str) -> dict:
        """Generate and store job description embedding."""
        logger.info("generate_job_embedding | job=%s", job_id)
        try:
            existing = await self.repo.get_job_embedding(job_id)
            if existing:
                return {"job_id": str(job_id), "message": "Job embedding already generated.", "vector_dims": len(existing.vector)}

            t_start = time.time()
            vector = await self.ollama.get_embedding(job_description[:3000])
            duration_ms = int((time.time() - t_start) * 1000)

            await self.repo.create_job_embedding(
                job_id=job_id,
                vector=vector,
                model_name="nomic-embed-text:latest",
            )

            await self.repo.create_ai_log(
                action="EMBEDDING",
                model_used="nomic-embed-text:latest",
                prompt_length=len(job_description),
                response_length=len(vector),
                duration_ms=duration_ms,
            )

            await self.session.commit()
            return {"job_id": str(job_id), "message": "Job embedding generated successfully.", "vector_dims": len(vector)}

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("generate_job_embedding: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 3 continued: Semantic Matching
    # ------------------------------------------------------------------

    async def match_candidate(self, resume_doc_id: uuid.UUID, job_id: uuid.UUID, job_description: str) -> SemanticMatchResponse:
        """Compute cosine similarity between resume and job description embeddings."""
        logger.info("match_candidate | doc=%s | job=%s", resume_doc_id, job_id)
        try:
            existing = await self.repo.get_candidate_similarity(resume_doc_id, job_id)
            if existing:
                return SemanticMatchResponse.model_validate({
                    "resume_document_id": existing.resume_document_id,
                    "job_id": existing.job_id,
                    "score": float(existing.score),
                    "matching_skills": existing.matching_skills,
                    "missing_skills": existing.missing_skills,
                })

            resume_emb = await self.repo.get_resume_embedding(resume_doc_id)
            if not resume_emb:
                raise AppException(message="Resume embedding not found. Run /embedding first.", status_code=status.HTTP_400_BAD_REQUEST)

            job_emb = await self.repo.get_job_embedding(job_id)
            if not job_emb:
                # Generate on the fly
                await self.generate_job_embedding(job_id, job_description)
                job_emb = await self.repo.get_job_embedding(job_id)

            score = cosine_similarity(resume_emb.vector, job_emb.vector)

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            candidate_skills = extract_skill_list(extracted.skills if extracted else {})
            matching, missing = find_matching_missing_skills(candidate_skills, job_description)

            sim = await self.repo.create_candidate_similarity(
                resume_document_id=resume_doc_id,
                job_id=job_id,
                score=score,
                matching_skills=matching,
                missing_skills=missing,
            )

            await self.session.commit()
            return SemanticMatchResponse(
                resume_document_id=resume_doc_id,
                job_id=job_id,
                score=round(score, 4),
                matching_skills=matching,
                missing_skills=missing,
            )

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("match_candidate: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 4: LLM Evaluation via Llama3
    # ------------------------------------------------------------------

    async def analyze_candidate(self, resume_doc_id: uuid.UUID, job_id: uuid.UUID, job_description: str) -> AiAnalysisResponse:
        """Run Llama3 qualitative analysis of candidate against job."""
        logger.info("analyze_candidate | doc=%s | job=%s", resume_doc_id, job_id)
        try:
            existing = await self.repo.get_candidate_analysis(resume_doc_id, job_id)
            if existing:
                return AiAnalysisResponse.model_validate(existing.__dict__)

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            if not extracted:
                raise AppException(message="Resume not extracted yet. Run /extract first.", status_code=status.HTTP_400_BAD_REQUEST)

            sim = await self.repo.get_candidate_similarity(resume_doc_id, job_id)
            match_score = float(sim.score) if sim else 0.5
            matching_skills = sim.matching_skills if sim else []
            missing_skills = sim.missing_skills if sim else []

            resume_text = f"Name: {extracted.name}\nSummary: {extracted.summary}\n{extracted.raw_text[:4000]}"

            t_start = time.time()
            prompt = ANALYSIS_USER_TEMPLATE.format(
                job_description=job_description[:2000],
                resume_text=resume_text,
                match_score=match_score,
                matching_skills=", ".join(matching_skills[:20]),
                missing_skills=", ".join(missing_skills[:20]),
            )
            llm_response = await self.ollama.generate_completion(
                prompt=prompt,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                json_format=True,
            )
            duration_ms = int((time.time() - t_start) * 1000)

            analysis = {}
            if llm_response:
                try:
                    analysis = json.loads(llm_response)
                except json.JSONDecodeError:
                    logger.warning("Llama3 analysis returned non-JSON, using defaults")

            # Build defaults if Ollama was not available or returned nothing
            professional_summary = analysis.get("professional_summary") or (
                f"{extracted.name or 'The candidate'} has experience in "
                f"{', '.join(matching_skills[:3]) if matching_skills else 'software engineering'}."
            )

            analysis_kwargs = {
                "resume_document_id": resume_doc_id,
                "job_id": job_id,
                "professional_summary": professional_summary,
                "strengths": analysis.get("strengths", matching_skills[:3] or ["Relevant experience"]),
                "weaknesses": analysis.get("weaknesses", missing_skills[:2] or []),
                "risk_factors": analysis.get("risk_factors", []),
                "hiring_recommendation": analysis.get("hiring_recommendation", "Maybe"),
                "culture_fit": analysis.get("culture_fit", "Requires further assessment."),
                "technical_fit": analysis.get("technical_fit", "Technical skills align partially with job requirements."),
                "communication_assessment": analysis.get("communication_assessment", "Average communication skills based on resume."),
                "career_progression": analysis.get("career_progression", "Steady career progression noted."),
                "skill_gaps": analysis.get("skill_gaps", missing_skills[:3] or []),
                "upskilling_suggestions": analysis.get("upskilling_suggestions", []),
                "confidence_score": float(analysis.get("confidence_score", 0.75)),
            }

            analysis_obj = await self.repo.create_candidate_analysis(**analysis_kwargs)

            await self.repo.create_ai_log(
                action="ANALYZE",
                model_used="llama3:latest",
                prompt_length=len(prompt),
                response_length=len(llm_response or ""),
                duration_ms=duration_ms,
            )

            await self.session.commit()
            return AiAnalysisResponse.model_validate(analysis_obj.__dict__)

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("analyze_candidate: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 5: Candidate Ranking
    # ------------------------------------------------------------------

    async def rank_candidate(self, resume_doc_id: uuid.UUID, job_id: uuid.UUID) -> CandidateRankingResponse:
        """Compute multi-dimensional ranking scores."""
        logger.info("rank_candidate | doc=%s | job=%s", resume_doc_id, job_id)
        try:
            existing = await self.repo.get_candidate_ranking(resume_doc_id, job_id)
            if existing:
                return CandidateRankingResponse.model_validate(existing.__dict__)

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            if not extracted:
                raise AppException(message="Resume not extracted yet. Run /extract first.", status_code=status.HTTP_400_BAD_REQUEST)

            sim = await self.repo.get_candidate_similarity(resume_doc_id, job_id)
            analysis_obj = await self.repo.get_candidate_analysis(resume_doc_id, job_id)

            analysis_dict = {}
            if analysis_obj:
                analysis_dict = {
                    "hiring_recommendation": analysis_obj.hiring_recommendation,
                    "communication_assessment": analysis_obj.communication_assessment,
                }

            extracted_dict = {
                "experience": extracted.experience or [],
                "education": extracted.education or [],
                "projects": extracted.projects or [],
                "certifications": extracted.certifications or [],
                "skills": extracted.skills or {},
            }

            scores = calculate_ranking_scores(
                similarity_score=float(sim.score) if sim else 0.5,
                extracted_data=extracted_dict,
                analysis=analysis_dict,
            )

            ranking = await self.repo.create_candidate_ranking(
                resume_document_id=resume_doc_id,
                job_id=job_id,
                **scores,
            )

            await self.session.commit()
            return CandidateRankingResponse.model_validate(ranking.__dict__)

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("rank_candidate: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 6: Interview Copilot Question Generator
    # ------------------------------------------------------------------

    async def generate_interview_questions(self, resume_doc_id: uuid.UUID, job_id: uuid.UUID, job_description: str) -> InterviewQuestionsResponse:
        """Generate targeted questions per candidate and job via Llama3."""
        logger.info("generate_interview_questions | doc=%s | job=%s", resume_doc_id, job_id)
        try:
            existing = await self.repo.get_interview_questions(resume_doc_id, job_id)
            if existing:
                return InterviewQuestionsResponse.model_validate(existing.__dict__)

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            if not extracted:
                raise AppException(message="Resume not extracted yet. Run /extract first.", status_code=status.HTTP_400_BAD_REQUEST)

            resume_summary = (
                f"Name: {extracted.name}\nSummary: {extracted.summary}\n"
                f"Skills: {json.dumps(extracted.skills or {})}\n"
                f"Experience: {json.dumps((extracted.experience or [])[:3])}\n"
                f"Education: {json.dumps(extracted.education or [])}"
            )

            t_start = time.time()
            prompt = INTERVIEW_USER_TEMPLATE.format(
                job_description=job_description[:2000],
                resume_summary=resume_summary[:2000],
            )
            llm_response = await self.ollama.generate_completion(
                prompt=prompt,
                system_prompt=INTERVIEW_SYSTEM_PROMPT,
                json_format=True,
            )
            duration_ms = int((time.time() - t_start) * 1000)

            questions_list = []
            if llm_response:
                try:
                    parsed = json.loads(llm_response)
                    questions_list = parsed.get("questions", [])
                except json.JSONDecodeError:
                    logger.warning("Interview generation returned non-JSON")

            # Fallback deterministic questions when Ollama not running
            if not questions_list:
                skill_list = extract_skill_list(extracted.skills or {})
                primary_skill = skill_list[0] if skill_list else "Python"
                questions_list = [
                    {"question": f"Explain how you used {primary_skill} in your most recent project.", "expected_answer": "Expects detailed practical experience.", "category": "Technical", "difficulty": "Medium", "checklist": ["Real project context", "Depth of usage", "Problem-solving"]},
                    {"question": "Describe a challenging technical problem you solved and your approach.", "expected_answer": "Systematic problem decomposition and analytical thinking.", "category": "Technical", "difficulty": "Hard", "checklist": ["Clear problem statement", "Step by step approach", "Outcome"]},
                    {"question": "How would you design a scalable REST API?", "expected_answer": "Should mention REST principles, pagination, caching, auth, rate limiting.", "category": "System Design", "difficulty": "Hard", "checklist": ["API design", "Scalability", "Security", "Performance"]},
                    {"question": "Write code to find the second largest element in an array.", "expected_answer": "O(n) optimal approach without sorting.", "category": "Coding", "difficulty": "Medium", "checklist": ["Correctness", "Edge cases", "Time complexity"]},
                    {"question": "Tell me about yourself and your career journey.", "expected_answer": "Structured narrative of professional growth.", "category": "HR", "difficulty": "Easy", "checklist": ["Clarity", "Relevance", "Confidence"]},
                ]

            iq = await self.repo.create_interview_questions(
                resume_document_id=resume_doc_id,
                job_id=job_id,
                questions=questions_list,
            )

            await self.repo.create_ai_log(
                action="INTERVIEW",
                model_used="llama3:latest",
                prompt_length=len(prompt),
                response_length=len(llm_response or ""),
                duration_ms=duration_ms,
            )

            await self.session.commit()
            return InterviewQuestionsResponse.model_validate(iq.__dict__)

        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("generate_interview_questions: error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Stage 7: Recruitment Dashboard
    # ------------------------------------------------------------------

    async def get_candidate_dashboard(self, resume_doc_id: uuid.UUID, job_id: uuid.UUID) -> AiCopilotDashboardView:
        """Aggregate all pipeline data into a unified dashboard view."""
        logger.info("get_candidate_dashboard | doc=%s | job=%s", resume_doc_id, job_id)
        try:
            doc = await self.repo.get_resume_document_by_id(resume_doc_id)
            if not doc:
                raise AppException(message="Resume document not found.", status_code=status.HTTP_404_NOT_FOUND)

            extracted = await self.repo.get_extracted_data(resume_doc_id)
            sim = await self.repo.get_candidate_similarity(resume_doc_id, job_id)
            analysis = await self.repo.get_candidate_analysis(resume_doc_id, job_id)
            ranking = await self.repo.get_candidate_ranking(resume_doc_id, job_id)
            iq_obj = await self.repo.get_interview_questions(resume_doc_id, job_id)

            overall_score = float(ranking.overall_score) if ranking else 0.0
            skill_match_pct = round(float(sim.score) * 100, 1) if sim else 0.0
            top_skills = extract_skill_list(extracted.skills if extracted else {})[:10]
            missing_skills = sim.missing_skills[:10] if sim else []

            career_timeline = []
            if extracted and extracted.experience:
                for exp in extracted.experience:
                    career_timeline.append({
                        "company": exp.get("company", "Unknown"),
                        "role": exp.get("role", "Unknown"),
                        "period": f"{exp.get('start_date', '')} - {exp.get('end_date', '')}",
                    })

            return AiCopilotDashboardView(
                overall_score=overall_score,
                technical_score=float(ranking.technical_score) if ranking else 0.0,
                experience_score=float(ranking.experience_score) if ranking else 0.0,
                education_score=float(ranking.education_score) if ranking else 0.0,
                project_score=float(ranking.project_score) if ranking else 0.0,
                communication_score=float(ranking.communication_score) if ranking else 0.0,
                leadership_score=float(ranking.leadership_score) if ranking else 0.0,
                culture_score=float(ranking.culture_score) if ranking else 0.0,
                skill_match_percentage=skill_match_pct,
                experience_match_percentage=float(ranking.experience_score) if ranking else 0.0,
                education_match_percentage=float(ranking.education_score) if ranking else 0.0,
                top_skills=top_skills,
                missing_skills=missing_skills,
                strengths=analysis.strengths if analysis else [],
                weaknesses=analysis.weaknesses if analysis else [],
                resume_summary=analysis.professional_summary if analysis else "Not analyzed yet.",
                career_timeline=career_timeline,
                ai_recommendation=analysis.hiring_recommendation if analysis else "Pending",
                interview_questions=iq_obj.questions[:5] if iq_obj else [],
                risk_analysis=analysis.risk_factors if analysis else [],
                confidence_score=float(analysis.confidence_score) if analysis else 0.0,
            )

        except AppException:
            raise
        except Exception as exc:
            logger.exception("get_candidate_dashboard: error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_job_rankings(self, job_id: uuid.UUID) -> list[dict]:
        """Retrieve ranked candidates list for a job, sorted best to worst."""
        try:
            rankings = await self.repo.list_job_rankings(job_id)
            result = []
            for idx, r in enumerate(rankings, start=1):
                extracted = await self.repo.get_extracted_data(r.resume_document_id)
                result.append({
                    "rank": idx,
                    "resume_document_id": str(r.resume_document_id),
                    "candidate_name": extracted.name if extracted else "Unknown",
                    "overall_score": float(r.overall_score),
                    "technical_score": float(r.technical_score),
                    "experience_score": float(r.experience_score),
                })
            return result
        except Exception as exc:
            logger.exception("get_job_rankings: error", exc_info=exc)
            raise DatabaseException() from exc

    async def run_copilot_tool(
        self,
        tool: str,
        job_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        user_input: str | None = None,
    ) -> str:
        from app.models.recruitment import Job, Candidate
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        job_details = ""
        candidate_details = ""
        
        if job_id:
            res_job = await self.session.execute(
                select(Job).where(Job.id == job_id).options(selectinload(Job.skills))
            )
            job = res_job.scalar_one_or_none()
            if job:
                skills_str = ", ".join([s.skill_name for s in job.skills])
                job_details = (
                    f"Job Title: {job.title}\n"
                    f"Job Description: {job.job_description}\n"
                    f"Department: {job.department}\n"
                    f"Skills Required: {skills_str}\n"
                    f"Location: {job.location}\n"
                    f"Salary Range: {job.min_salary or 0} - {job.max_salary or 0}"
                )
        
        if candidate_id:
            res_cand = await self.session.execute(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            candidate = res_cand.scalar_one_or_none()
            if candidate:
                skills_str = ", ".join(candidate.skills or [])
                candidate_details = (
                    f"Candidate Name: {candidate.first_name} {candidate.last_name}\n"
                    f"Skills: {skills_str}\n"
                    f"Summary: {candidate.summary or ''}\n"
                    f"Location: {candidate.location}\n"
                    f"Notice Period: {candidate.notice_days} days\n"
                    f"Expected Salary: {candidate.expected_salary or 0}\n"
                    f"Years of Experience: {candidate.years_experience}"
                )
        
        prompt = f"""You are an advanced AI Recruiting Assistant. Please perform the following task:
Tool/Task: {tool}
User Instruction: {user_input or "none"}

Context Details:
[Job Description Context]
{job_details or "No job context selected."}

[Candidate Profile Context]
{candidate_details or "No candidate context selected."}

Please generate the specific recruiter outcome. Be precise, clear, and professional. Return raw text/markdown without code blocks or HTML."""

        res = await self.ollama.generate_completion(prompt=prompt)
        return res or "AI failed to generate response."


async def get_ai_copilot_service(
    session: AsyncSession = Depends(get_db_session),
) -> AiCopilotService:
    return AiCopilotService(
        session=session,
        repo=AiCopilotRepository(session),
        ollama=ollama_client,
    )
