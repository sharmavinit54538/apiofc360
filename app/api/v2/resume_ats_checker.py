"""Resume ATS Checker API v2 — Real-time AI ATS evaluation and detailed scoring report for all authenticated users."""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.core.config import settings
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.ats_scoring_service import ATSScoringService
from app.services.resume_ocr_service import ResumeOCRService
from app.services.resume_parser_service import ResumeParserService
from app.services.resume_quality_service import ResumeQualityService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/resume-ats-checker",
    tags=["Resume ATS Checker"],
)

ALLOWED_EXTENSIONS = set(settings.ALLOWED_RESUME_EXTENSIONS)
MAX_SIZE = settings.MAX_RESUME_SIZE_MB * 1024 * 1024


@router.post(
    "/check",
    response_model=APIResponse[dict[str, Any]],
    summary="Check resume ATS score and get detailed diagnostic report",
    description="""
Upload any resume file (PDF, DOCX, DOC, JPG, PNG, JPEG, TIFF) and receive an instant,
real ATS evaluation.

**Analysis Pipeline:**
1. File validation (extension & size limit)
2. OCR & Document text extraction via `ResumeOCRService`
3. AI structured entity parsing via `ResumeParserService` (LLM-based)
4. Quality & formatting diagnostic via `ResumeQualityService`
5. Dynamic weighted ATS calculation & job compatibility via `ATSScoringService`
6. Actionable recommendations & gap breakdown
""",
)
async def check_resume_ats(
    file: UploadFile,
    job_title: str | None = Form(None, description="Target job title (optional)"),
    job_description: str | None = Form(None, description="Target job description (optional)"),
    required_skills: str | None = Form(None, description="Comma-separated required skills (optional)"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict[str, Any]]:
    """Evaluate a resume against ATS algorithms and generate an exhaustive diagnostic report."""
    # 1. Validate File Extension
    file_name = file.filename or "resume"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File type '{ext}' is not supported. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 2. Validate File Size
    content = await file.read()
    if not content or len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded file is empty. Please upload a valid resume document.",
        )

    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the maximum limit of {settings.MAX_RESUME_SIZE_MB}MB.",
        )

    # 3. Extract Raw Text using ResumeOCRService
    ocr_service = ResumeOCRService()
    mime_type = file.content_type or "application/octet-stream"

    try:
        ocr_result = await ocr_service.extract_text(
            file_bytes=content,
            file_name=file_name,
            mime_type=mime_type,
        )
    except Exception as exc:
        logger.error("Text extraction failed for '%s': %s", file_name, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to extract text from '{file_name}'. The file may be password protected or corrupt.",
        )

    raw_text = (ocr_result.get("raw_text") or "").strip()
    ocr_engine = ocr_result.get("ocr_engine", "unknown")

    # Readability validation
    if not raw_text or len(raw_text) < 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded resume contains unreadable or insufficient text. Please provide a clear, readable document.",
        )

    # 4. Structured Entity Extraction via LLM Parser
    parser_service = ResumeParserService()
    try:
        parsed_data = await parser_service.parse_resume(raw_text)
    except Exception as exc:
        logger.error("ResumeParserService error: %s", exc)
        # Fallback to minimal parsed structure if LLM error occurs
        parsed_data = parser_service._empty_result()

    # 5. Quality & Formatting Analysis
    quality_service = ResumeQualityService()
    quality_result = quality_service.analyze_quality(
        raw_text=raw_text,
        parsed_data=parsed_data,
        ocr_engine=ocr_engine,
    )

    if not quality_result.get("is_readable", True):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Resume document is unreadable or blank. Please upload a clear PDF or DOCX file.",
        )

    formatting_score = float(quality_result.get("formatting_score", 85.0))
    issues = quality_result.get("issues", [])
    missing_fields = quality_result.get("missing_fields", [])

    # 6. ATS Scoring & Match Calculation
    parsed_skills_list: list[str] = []
    if required_skills:
        parsed_skills_list = [s.strip() for s in required_skills.split(",") if s.strip()]

    has_job_context = bool(
        (job_title and job_title.strip())
        or (job_description and job_description.strip())
        or parsed_skills_list
    )

    job_data: dict[str, Any] = {
        "title": (job_title or "").strip(),
        "job_description": (job_description or "").strip(),
        "skills": parsed_skills_list,
    }

    scoring_service = ATSScoringService()
    ats_result = scoring_service.calculate_ats_score(
        candidate_data={
            **parsed_data,
            "raw_text": raw_text,
        },
        job_data=job_data,
        formatting_score=formatting_score,
    )

    # 7. Actionable Recommendations Generation
    recommendations: list[str] = list(ats_result.get("recommendations", []))

    # Add recommendations based on quality issues and missing sections
    if "email" in missing_fields:
        recommendations.append("Add a clear email address in your contact header.")
    if "phone" in missing_fields:
        recommendations.append("Include your contact phone number for recruiter outreach.")
    if "skills" in missing_fields:
        recommendations.append("Add a dedicated 'Skills' section with categorized technical and soft skills.")
    if "education" in missing_fields:
        recommendations.append("Include your education details (degree, major, institution, graduation year).")
    if not parsed_data.get("projects"):
        recommendations.append("Add 2-3 key technical projects with quantifiable results and technologies used.")
    if not parsed_data.get("certifications"):
        recommendations.append("List relevant certifications to boost credibility in your domain.")
    if formatting_score < 70:
        recommendations.append("Simplify resume formatting: avoid complex tables, unusual graphics, or nested text boxes.")
    if not has_job_context:
        recommendations.append("Tip: Provide a target Job Title or Job Description to get customized role-fit and keyword matching scores.")

    # Deduplicate recommendations preserving order
    clean_recommendations: list[str] = []
    seen_rec: set[str] = set()
    for rec in recommendations:
        rec_clean = rec.strip()
        if rec_clean and rec_clean.lower() not in seen_rec:
            seen_rec.add(rec_clean.lower())
            clean_recommendations.append(rec_clean)

    # 8. Construct Comprehensive Response Payload
    overall_ats_score = float(ats_result.get("overall_ats_score", 0.0))
    job_match_score = float(ats_result.get("job_match", 0.0)) if has_job_context else None

    response_payload = {
        "ats_score": round(overall_ats_score, 1),
        "job_match_score": round(job_match_score, 1) if job_match_score is not None else None,
        "has_job_context": has_job_context,
        "formatting_score": round(formatting_score, 1),
        "score_breakdown": ats_result.get("score_breakdown", {}),
        "category_scores": {
            "skills": round(float(ats_result.get("skill_match_score", 0.0)), 1),
            "experience": round(float(ats_result.get("experience_match_score", 0.0)), 1),
            "education": round(float(ats_result.get("education_match_score", 0.0)), 1),
            "keywords": round(float(ats_result.get("keyword_match_score", 0.0)), 1),
            "projects": round(float(ats_result.get("projects_score", 0.0)), 1),
            "certifications": round(float(ats_result.get("certifications_score", 0.0)), 1),
            "resume_quality": round(float(ats_result.get("resume_quality_score", 0.0)), 1),
        },
        "matched_skills": ats_result.get("matched_skills", []),
        "missing_skills": ats_result.get("missing_skills", []),
        "extra_skills": ats_result.get("extra_skills", []),
        "issues": issues,
        "missing_fields": missing_fields,
        "parsed_resume": {
            "name": parsed_data.get("candidate_name") or parsed_data.get("name"),
            "email": parsed_data.get("email"),
            "phone": parsed_data.get("phone"),
            "address": parsed_data.get("address") or parsed_data.get("current_location"),
            "linkedin": parsed_data.get("linkedin"),
            "github": parsed_data.get("github"),
            "portfolio": parsed_data.get("portfolio"),
            "summary": parsed_data.get("summary", ""),
            "experience_years": round(float(parsed_data.get("total_experience_years") or 0.0), 1),
            "current_company": parsed_data.get("current_company"),
            "current_designation": parsed_data.get("current_designation"),
            "skills": parsed_data.get("skills", []),
            "technical_skills": parsed_data.get("technical_skills", []),
            "soft_skills": parsed_data.get("soft_skills", []),
            "education": parsed_data.get("education", []),
            "projects": parsed_data.get("projects", []),
            "certifications": parsed_data.get("certifications", []),
            "languages": parsed_data.get("languages", []),
        },
        "recommendations": clean_recommendations,
        "meta": {
            "file_name": file_name,
            "file_size_bytes": len(content),
            "char_count": len(raw_text),
            "ocr_engine_used": ocr_engine,
        },
    }

    return APIResponse[dict[str, Any]](
        success=True,
        message="Resume ATS analysis completed successfully.",
        data=response_payload,
        errors=None,
    )
