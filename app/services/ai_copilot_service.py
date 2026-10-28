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

    async def salary_negotiation_copilot(
        self,
        *,
        company_id: uuid.UUID,
        band_id: uuid.UUID,
        candidate_match_score: float,
        hiring_budget_annual_paise: int,
        candidate_name: str = "Candidate",
        expected_ctc_annual_paise: int | None = None,
        reference_employee_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Build three auditable CTC scenarios from a tenant compensation band.

        No market or employee salary data is inferred by an LLM.  Amounts remain
        integer minor units, every scenario is capped by the approved hiring
        budget, and the resulting compa-ratio is shown for compensation review.
        """
        from decimal import Decimal, ROUND_HALF_UP
        from sqlalchemy import select
        from app.models.compensation import CompensationBand
        from app.services.compensation_service import CompensationService

        if not 0 <= float(candidate_match_score) <= 1:
            raise ValueError("candidate_match_score must be between 0 and 1.")
        if int(hiring_budget_annual_paise) < 0:
            raise ValueError("hiring_budget_annual_paise cannot be negative.")
        band = (await self.session.execute(select(CompensationBand).where(
            CompensationBand.id == band_id,
            CompensationBand.company_id == company_id,
            CompensationBand.is_active.is_(True),
        ))).scalar_one_or_none()
        if band is None:
            raise LookupError("Compensation band not found in the current tenant.")
        if not 0 <= band.min_paise <= band.mid_paise <= band.max_paise:
            raise ValueError("Compensation band minimum, midpoint and maximum are inconsistent.")

        score = Decimal(str(candidate_match_score))
        minimum, midpoint, maximum = (Decimal(band.min_paise), Decimal(band.mid_paise), Decimal(band.max_paise))
        budget = Decimal(int(hiring_budget_annual_paise))
        conservative = minimum + (midpoint - minimum) * max(Decimal("0"), score - Decimal("0.5"))
        recommended = midpoint * (Decimal("0.90") + Decimal("0.20") * score)
        if expected_ctc_annual_paise is not None:
            if expected_ctc_annual_paise < 0:
                raise ValueError("expected_ctc_annual_paise cannot be negative.")
            # Expectations inform, but never move a package outside its band.
            expected = min(maximum, max(minimum, Decimal(expected_ctc_annual_paise)))
            recommended = (recommended + expected) / 2
        stretch = max(recommended, midpoint + (maximum - midpoint) * (Decimal("0.50") + score / 2))

        reference = None
        if reference_employee_id is not None:
            reference = await CompensationService(self.session).compa_ratio(
                company_id=company_id, employee_id=reference_employee_id,
            )

        scenario_specs = (
            ("CONSERVATIVE", conservative, Decimal("0.95"), Decimal("0.00")),
            ("RECOMMENDED", recommended, Decimal("0.90"), Decimal("0.02")),
            ("STRETCH", stretch, Decimal("0.85"), Decimal("0.03")),
        )
        scenarios = []
        for name, raw_amount, fixed_ratio, signing_ratio in scenario_specs:
            amount = int(min(budget, maximum, max(minimum, raw_amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            signing = int((Decimal(amount) * signing_ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            variable = int((Decimal(amount - signing) * (Decimal("1") - fixed_ratio)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            fixed = amount - signing - variable
            ratio = (Decimal(amount) / midpoint).quantize(Decimal("0.0001")) if midpoint else Decimal("0")
            band_position = "BELOW_BAND" if amount < band.min_paise else "ABOVE_BAND" if amount > band.max_paise else "WITHIN_BAND"
            amount_text = f"{amount / 100:,.2f} {band.currency}"
            within_band = band_position == "WITHIN_BAND"
            opening = (
                f"We can offer a total annual CTC of {amount_text}, structured within the approved {band.grade} band."
                if within_band else
                f"The budget-constrained scenario of {amount_text} is {band_position.lower().replace('_', ' ')} and is not issuable without a documented band and budget review."
            )
            concession_guardrail = (
                "Any increase requires compensation approval and must remain within the band and hiring budget."
                if within_band else
                "Do not issue this scenario: restore a band-compliant budget or obtain a documented compensation-band exception first."
            )
            scenarios.append({
                "scenario": name,
                "ctc_annual_paise": amount,
                "currency": band.currency,
                "fixed_ctc_annual_paise": fixed,
                "variable_pay_annual_paise": variable,
                "signing_bonus_paise": signing,
                "compa_ratio": float(ratio),
                "band_position": band_position,
                "budget_utilization_pct": float((Decimal(amount) * 100 / budget).quantize(Decimal("0.01"))) if budget else None,
                "within_budget": amount <= hiring_budget_annual_paise,
                "issuable_without_band_exception": within_band,
                "negotiation_script": {
                    "opening": opening,
                    "candidate_expectation_response": "The package reflects role match, internal equity and the approved budget; let us discuss fixed pay, variable pay and joining support separately.",
                    "concession_guardrail": concession_guardrail,
                    "close": "If the overall structure works for you, we will route this exact scenario for written approval before issuing an offer.",
                },
            })

        return {
            "company_id": str(company_id),
            "candidate_name": candidate_name,
            "band": {
                "id": str(band.id), "code": band.band_code, "grade": band.grade,
                "min_paise": band.min_paise, "mid_paise": band.mid_paise,
                "max_paise": band.max_paise, "currency": band.currency,
            },
            "candidate_match_score": float(score),
            "hiring_budget_annual_paise": int(hiring_budget_annual_paise),
            "budget_feasible_for_band": hiring_budget_annual_paise >= band.min_paise,
            "reference_internal_compa_ratio": reference,
            "scenarios": scenarios,
            "decision_support_only": True,
            "requires_compensation_approval": True,
        }

    async def disciplinary_case_assistant(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        incident_summary: str,
        incident_date: str,
        policy_query: str | None = None,
    ) -> dict[str, Any]:
        """Draft a policy-grounded show-cause pack without deciding guilt."""
        import re
        from sqlalchemy import select
        from app.models.employee import Employee
        from app.models.grievance_posh import GrievanceCase
        from app.models.policy import CompanyPolicyChunk, CompanyPolicyDocument
        from app.rag.hr_copilot_rag import get_hr_copilot

        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False),
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Employee not found in the current tenant.")
        incident_summary = incident_summary.strip()
        if len(incident_summary) < 10:
            raise ValueError("A factual incident summary of at least 10 characters is required.")

        documents = (await self.session.execute(select(CompanyPolicyDocument).where(
            CompanyPolicyDocument.company_id == company_id,
            CompanyPolicyDocument.status.in_(("PUBLISHED", "ACTIVE", "APPROVED")),
        ))).scalars().all()
        policy_rows: list[dict[str, Any]] = []
        for document in documents:
            chunks = (await self.session.execute(select(CompanyPolicyChunk).where(
                CompanyPolicyChunk.policy_document_id == document.id,
            ).order_by(CompanyPolicyChunk.chunk_order))).scalars().all()
            if chunks:
                for chunk in chunks:
                    policy_rows.append({
                        "company_id": company_id, "policy_document_id": document.id,
                        "title": document.title, "category": document.category,
                        "version_number": document.version_number,
                        "chunk_order": chunk.chunk_order, "chunk_text": chunk.chunk_text,
                    })
            else:
                # Unchunked, published standing orders remain usable with exact
                # excerpts; no fabricated fallback handbook is introduced.
                policy_rows.append({
                    "company_id": company_id, "policy_document_id": document.id,
                    "title": document.title, "category": document.category,
                    "version_number": document.version_number,
                    "chunk_order": 0, "raw_content": document.raw_content,
                })
        query = policy_query or f"discipline misconduct show cause inquiry {incident_summary}"
        grounding = await get_hr_copilot().ground_policy_query(
            company_id=company_id, question=query, documents=policy_rows, top_k=5,
        )

        # Precedents are metadata/outcome comparisons only.  Confidential case
        # narratives and reporter identities are never copied into the response.
        precedents = (await self.session.execute(select(GrievanceCase).where(
            GrievanceCase.company_id == company_id,
            GrievanceCase.status.in_(("RESOLVED", "CLOSED", "APPEAL_RESOLVED")),
        ).order_by(GrievanceCase.resolved_at.desc()).limit(50))).scalars().all()
        terms = set(re.findall(r"[a-z0-9]+", incident_summary.lower()))
        precedent_rows = []
        for case in precedents:
            case_terms = set(re.findall(r"[a-z0-9]+", f"{case.category} {case.subject}".lower()))
            similarity = len(terms & case_terms) / max(1, len(terms | case_terms))
            precedent_rows.append({
                "case_number": case.case_number, "category": case.category,
                "status": case.status, "resolution": case.resolution,
                "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
                "similarity_score": round(similarity, 4),
            })
        precedent_rows.sort(key=lambda row: (-row["similarity_score"], row["case_number"]))

        citations = grounding["citations"]
        clause_lines = "\n".join(
            f"- {item['document']}, {item['section']} (version {item['version']}): {item['excerpt']}"
            for item in citations
        ) or "- [INSERT VERIFIED POLICY CLAUSE BEFORE ISSUE]"
        employee_name = f"{employee.first_name} {employee.last_name}".strip()
        notice = (
            f"DRAFT SHOW-CAUSE NOTICE — NOT FOR ISSUE WITHOUT HR/LEGAL REVIEW\n\n"
            f"To: {employee_name} ({employee.employee_id})\n"
            f"Incident date: {incident_date}\n\n"
            f"It is alleged that: {incident_summary}\n\n"
            f"Potentially applicable policy passages:\n{clause_lines}\n\n"
            "You are requested to submit your written explanation and any supporting material within the period confirmed by HR. "
            "You may inspect the relied-upon evidence and present your response during the inquiry. "
            "This notice records an allegation, not a finding of misconduct. No disciplinary penalty is predetermined."
        )
        checklist = [
            {"step": 1, "action": "Preserve original evidence and record a chain of custody.", "owner": "HR / IT"},
            {"step": 2, "action": "Verify the applicable published policy version and jurisdiction-specific standing orders.", "owner": "HR / Legal"},
            {"step": 3, "action": "Issue an allegation-specific show-cause notice with reasonable response time and evidence access.", "owner": "HR"},
            {"step": 4, "action": "Appoint an impartial inquiry officer and check conflicts of interest.", "owner": "HR / Legal"},
            {"step": 5, "action": "Allow the employee to present evidence, witnesses and questions; document the proceedings.", "owner": "Inquiry officer"},
            {"step": 6, "action": "Compare only relevant, non-confidential precedents and assess proportionality.", "owner": "HR / Legal"},
            {"step": 7, "action": "Record findings separately from allegations and obtain required approvals before any action.", "owner": "Disciplinary authority"},
        ]
        return {
            "company_id": str(company_id), "employee_id": str(employee_id),
            "grounding_status": grounding["grounding_status"],
            "policy_answer": grounding["answer"], "policy_citations": citations,
            "show_cause_notice": notice,
            "inquiry_checklist": checklist,
            "precedent_comparisons": precedent_rows[:5],
            "allegation_not_finding": True,
            "requires_legal_review": True,
            "warnings": ([] if citations else ["No published policy evidence was retrieved; the notice contains a mandatory clause placeholder."]),
        }

    async def termination_risk_assistant(
        self,
        *,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        termination_reason: str,
        proposed_last_working_date: Any,
        notice_period_days: int = 30,
        notice_days_served: int = 0,
        maternity_protected: bool | None = None,
        is_workman: bool | None = None,
        as_of_date: Any = None,
    ) -> dict[str, Any]:
        """Estimate termination process risk and statutory payment components.

        This is an HR decision-support estimator, not a legal conclusion.  Active
        employee-relations cases are re-read from tenant tables on every call;
        callers cannot suppress those protections with request flags.
        """
        from datetime import date, datetime
        from decimal import Decimal, ROUND_HALF_UP
        from sqlalchemy import select
        from app.models.employee import Employee
        from app.models.grievance_posh import GrievanceCase, POSHComplaint
        from app.models.payroll import SalaryStructure
        from app.models.payroll_models import Compensation

        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False),
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Employee not found in the current tenant.")
        today = as_of_date or date.today()
        if isinstance(today, datetime):
            today = today.date()
        proposed_date = proposed_last_working_date
        if isinstance(proposed_date, str):
            proposed_date = date.fromisoformat(proposed_date)
        if proposed_date < today:
            raise ValueError("proposed_last_working_date cannot be before as_of_date.")
        if not 0 <= notice_period_days <= 365 or not 0 <= notice_days_served <= 365:
            raise ValueError("Notice days must be between 0 and 365.")
        if len(termination_reason.strip()) < 5:
            raise ValueError("A documented termination reason is required.")

        tenure_days = max(0, (today - employee.joining_date).days)
        tenure_months = int(Decimal(tenure_days) / Decimal("30.4375"))
        completed_years = tenure_days // 365
        metadata = employee.role_metadata if isinstance(employee.role_metadata, dict) else {}
        # Request flags can add HR-reviewed context, but cannot suppress a
        # protection/classification already present on the employee record.
        maternity = bool(metadata.get("maternity_protected", False)) or bool(maternity_protected)
        workman = str(employee.employee_category or "").strip().upper() in {"WORKMAN", "WORKMEN"} or bool(is_workman)
        retrenchment = "retrench" in termination_reason.lower() or "redundan" in termination_reason.lower()

        closed_statuses = {"CLOSED", "RESOLVED", "REJECTED", "WITHDRAWN", "APPEAL_RESOLVED"}
        grievances = (await self.session.execute(select(GrievanceCase).where(
            GrievanceCase.company_id == company_id,
        ))).scalars().all()
        posh_cases = (await self.session.execute(select(POSHComplaint).where(
            POSHComplaint.company_id == company_id,
        ))).scalars().all()

        def involves_employee(case: Any) -> bool:
            if case.reporter_employee_id == employee.id:
                return True
            accused = {str(value) for value in (case.accused_user_ids or [])}
            return str(employee.id) in accused or (employee.user_id is not None and str(employee.user_id) in accused)

        active_grievances = [case for case in grievances if case.status not in closed_statuses and involves_employee(case)]
        active_posh = [case for case in posh_cases if case.status not in closed_statuses and involves_employee(case)]
        active_case_count = len(active_grievances) + len(active_posh)

        compensation = (await self.session.execute(select(Compensation).where(
            Compensation.company_id == company_id, Compensation.employee_id == employee.id,
            Compensation.status == "ACTIVE",
        ).order_by(Compensation.effective_date.desc()).limit(1))).scalar_one_or_none()
        salary = None
        monthly_wage_paise = 0
        currency = "INR"
        if compensation is not None:
            monthly_wage_paise = int(round(Decimal(compensation.ctc_annual_paise) / 12))
            currency = getattr(compensation, "currency", "INR") or "INR"
        else:
            salary = (await self.session.execute(select(SalaryStructure).where(
                SalaryStructure.company_id == company_id, SalaryStructure.employee_id == employee.id,
                SalaryStructure.is_active.is_(True),
            ).order_by(SalaryStructure.effective_from.desc()).limit(1))).scalar_one_or_none()
            if salary is not None:
                monthly_wage_paise = int(round(Decimal(str(salary.basic_monthly + salary.hra_monthly + salary.special_allowance_monthly)) * 100))
                currency = getattr(salary, "currency", "INR") or "INR"
        shortfall_days = max(0, notice_period_days - notice_days_served)
        notice_compensation_paise = int((Decimal(monthly_wage_paise) * shortfall_days / 30).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        retrenchment_applicable = bool(workman and retrenchment and completed_years >= 1)
        retrenchment_compensation_paise = int((Decimal(monthly_wage_paise) * completed_years * 15 / 30).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if retrenchment_applicable else 0

        score = 10
        factors = [{"factor": "DOCUMENTED_PROCESS", "points": 10, "detail": "Every involuntary exit requires documented reason, evidence and approval."}]
        if tenure_months < 12:
            score += 10
            factors.append({"factor": "SHORT_TENURE", "points": 10, "detail": "Verify probation/confirmation and contract terms."})
        if maternity:
            score += 45
            factors.append({"factor": "MATERNITY_PROTECTION", "points": 45, "detail": "Potential statutory protection requires specialist legal review."})
        if active_case_count:
            protection_points = min(45, 30 + active_case_count * 5)
            score += protection_points
            factors.append({"factor": "ACTIVE_POSH_OR_GRIEVANCE", "points": protection_points, "detail": f"{active_case_count} active protected case(s) involve this employee."})
        if retrenchment_applicable:
            score += 20
            factors.append({"factor": "WORKMAN_RETRENCHMENT", "points": 20, "detail": "Workman retrenchment conditions and compensation must be verified."})
        if shortfall_days and not notice_compensation_paise:
            score += 10
            factors.append({"factor": "UNRESOLVED_NOTICE_SHORTFALL", "points": 10, "detail": "Notice shortfall has no calculated wage coverage."})
        score = min(100, score)
        level = "LOW" if score < 25 else "MEDIUM" if score < 50 else "HIGH" if score < 75 else "CRITICAL"
        checklist = [
            "Verify employment contract, applicable standing orders and current jurisdiction with counsel.",
            "Document the reason, supporting evidence, objective selection criteria and approval trail.",
            "Offer any contractually or statutorily required hearing and review retaliation risks.",
            "Reconcile notice, earned leave, retrenchment and other final dues before the last working day.",
        ]
        if maternity:
            checklist.insert(0, "Pause action until maternity-protection and prohibited-timing rules are reviewed by specialist counsel.")
        if active_case_count:
            checklist.insert(0, "Coordinate with the independent POSH/grievance owner; do not alter or close the protected case through this workflow.")
        if retrenchment_applicable:
            checklist.append("Validate government notice/permission, seniority and retrenchment-compensation rules before proceeding.")
        return {
            "company_id": str(company_id), "employee_id": str(employee_id),
            "as_of_date": today.isoformat(), "tenure_months": tenure_months,
            "completed_years": completed_years,
            "protected_employment_flags": {
                "maternity_protected": maternity, "active_posh_or_grievance": bool(active_case_count),
                "active_case_count": active_case_count, "is_workman": workman,
            },
            "risk_score": score, "risk_level": level, "risk_factors": factors,
            "notice": {
                "required_days": notice_period_days, "served_days": notice_days_served,
                "shortfall_days": shortfall_days, "compensation_paise": notice_compensation_paise,
            },
            "retrenchment": {
                "applicable_estimate": retrenchment_applicable,
                "completed_years_used": completed_years if retrenchment_applicable else 0,
                "compensation_paise": retrenchment_compensation_paise,
            },
            "monthly_wage_basis_paise": monthly_wage_paise, "currency": currency,
            "total_estimated_notice_and_retrenchment_paise": notice_compensation_paise + retrenchment_compensation_paise,
            "mitigation_checklist": checklist,
            "requires_legal_review": bool(maternity or active_case_count or retrenchment_applicable or score >= 50),
            "estimator_not_legal_advice": True,
        }


async def get_ai_copilot_service(
    session: AsyncSession = Depends(get_db_session),
) -> AiCopilotService:
    return AiCopilotService(
        session=session,
        repo=AiCopilotRepository(session),
        ollama=ollama_client,
    )
