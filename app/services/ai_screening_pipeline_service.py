"""Master Orchestrator Service for AI Resume Screening & ATS Matching Pipeline."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore, AIScreeningResult
from app.repositories.ai_recruitment_repository import AIRecruitmentRepository
from app.schemas.ai_resume import (
    AIInsightsSchema,
    ATSScoreBreakdownSchema,
    CandidateScreeningResponse,
    DuplicateDetectionSchema,
    ParsedResumeSchema,
    QualityAnalysisSchema,
)
from app.services.ats_scoring_service import ATSScoringService
from app.services.candidate_ranking_service import CandidateRankingService
from app.services.duplicate_detector_service import DuplicateDetectorService
from app.services.resume_cleaner_service import ResumeCleanerService
from app.services.resume_ocr_service import ResumeOCRService
from app.services.resume_parser_service import ResumeParserService
from app.services.resume_quality_service import ResumeQualityService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class AIScreeningPipelineService:
    """Master service executing end-to-end resume upload, OCR, parsing, ATS scoring, candidate ranking, and AI insights."""

    def __init__(
        self,
        session: AsyncSession,
        repo: AIRecruitmentRepository | None = None,
        storage_service: StorageService | None = None,
        ocr_service: ResumeOCRService | None = None,
        parser_service: ResumeParserService | None = None,
        cleaner_service: ResumeCleanerService | None = None,
        quality_service: ResumeQualityService | None = None,
        duplicate_service: DuplicateDetectorService | None = None,
        ats_service: ATSScoringService | None = None,
        ranking_service: CandidateRankingService | None = None,
    ) -> None:
        self.session = session
        self.repo = repo or AIRecruitmentRepository(session)
        self.storage_service = storage_service or StorageService()
        self.ocr_service = ocr_service or ResumeOCRService()
        self.parser_service = parser_service or ResumeParserService()
        self.cleaner_service = cleaner_service or ResumeCleanerService()
        self.quality_service = quality_service or ResumeQualityService()
        self.duplicate_service = duplicate_service or DuplicateDetectorService(session)
        self.ats_service = ats_service or ATSScoringService()
        self.ranking_service = ranking_service or CandidateRankingService()

    async def process_resume_upload(
        self,
        file: UploadFile,
        job_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        uploaded_by: uuid.UUID | None = None,
    ) -> CandidateScreeningResponse:
        """Process uploaded resume file end-to-end."""
        logger.info("Pipeline started for uploaded resume file=%s | job_id=%s", file.filename, job_id)

        # 1. Save file to storage
        saved_file = await self.storage_service.save_file(file)

        # 2. Extract OCR Raw Text
        ocr_res = await self.ocr_service.extract_text(
            file_bytes=saved_file["file_bytes"],
            file_name=saved_file["original_filename"],
            mime_type=saved_file["mime_type"],
        )
        raw_text = ocr_res["raw_text"]
        ocr_engine = ocr_res["ocr_engine"]

        # 3. Parse Resume (async LLM call)
        parsed_raw = await self.parser_service.parse_resume(raw_text)

        # 4. Clean & Normalize Data
        parsed_clean = self.cleaner_service.clean_parsed_data(parsed_raw, raw_text=raw_text)

        # 5. Quality Analysis
        quality_res = self.quality_service.analyze_quality(
            raw_text=raw_text,
            parsed_data=parsed_clean,
            ocr_engine=ocr_engine,
        )

        # 6. Duplicate Detection
        dup_res = await self.duplicate_service.check_duplicate(
            email=parsed_clean.get("email"),
            phone=parsed_clean.get("phone"),
            name=parsed_clean.get("candidate_name"),
            linkedin=parsed_clean.get("linkedin"),
            company=parsed_clean.get("current_company"),
            company_id=company_id,
        )

        # 7. Get Job Data & ATS Score Calculation
        job_data = {}
        target_title = "Target Position"
        if job_id:
            job_obj = await self.repo.get_job_by_id(job_id)
            if job_obj:
                target_title = job_obj.title
                job_skills = []
                if hasattr(job_obj, "skills") and job_obj.skills:
                    job_skills = [getattr(s, "skill_name", getattr(s, "name", "")) for s in job_obj.skills if getattr(s, "skill_name", getattr(s, "name", None))]
                job_data = {
                    "title": job_obj.title,
                    "job_description": getattr(job_obj, "job_description", "") or "",
                    "min_experience": getattr(job_obj, "min_experience", getattr(job_obj, "min_experience_years", 0.0)) or 0.0,
                    "skills": job_skills,
                }

        if not job_data:
            job_data = {
                "title": target_title,
                "job_description": "",
                "min_experience": 0.0,
                "skills": [],
            }

        ats_breakdown = self.ats_service.calculate_ats_score(
            candidate_data=parsed_clean,
            job_data=job_data,
            formatting_score=quality_res["formatting_score"],
        )
        ats_score = ats_breakdown["overall_ats_score"]

        # 8. Candidate Ranking & AI Insights
        ai_insights = self.ranking_service.generate_ai_insights(
            candidate_name=parsed_clean.get("candidate_name") or "Candidate",
            ats_score=ats_score,
            ats_breakdown=ats_breakdown,
            parsed_data=parsed_clean,
            job_title=target_title,
        )
        match_tier = self.ranking_service.determine_match_tier(ats_score)

        # 9. Save Candidate record in DB
        candidate = await self.repo.get_or_create_candidate(
            name=parsed_clean.get("candidate_name") or "Candidate",
            email=parsed_clean.get("email"),
            phone=parsed_clean.get("phone"),
            company_id=company_id,
            current_company=parsed_clean.get("current_company"),
            current_role=parsed_clean.get("current_designation"),
            years_experience=parsed_clean.get("total_experience_years") or 0.0,
            skills=parsed_clean.get("skills") or [],
            location=parsed_clean.get("current_location") or parsed_clean.get("address"),
            resume_path=saved_file["file_path"],
            resume_name=saved_file["original_filename"],
        )

        # 10. Save AIResumeDocument record
        resume_doc = AIResumeDocument(
            candidate_id=candidate.id,
            file_path=saved_file["file_path"],
            file_name=saved_file["original_filename"],
            file_size=saved_file["file_size"],
            file_type=saved_file["mime_type"],
            parse_status="COMPLETED",
            ocr_engine_used=ocr_engine,
            raw_text=raw_text,
            parsed_data=parsed_clean,
            candidate_name=parsed_clean.get("candidate_name"),
            candidate_email=parsed_clean.get("email"),
            years_experience=parsed_clean.get("total_experience_years"),
            uploaded_by=uploaded_by,
        )
        resume_doc = await self.repo.create_resume_document(resume_doc)

        # 11. Save CandidateMatchScore record
        confidence_val = float(parsed_raw.get("parsing_confidence") or 0.95)
        match_score_obj = CandidateMatchScore(
            resume_document_id=resume_doc.id,
            job_id=job_id or uuid.uuid4(),
            candidate_id=candidate.id,
            overall_match_score=ats_score / 100.0 if ats_score > 1.0 else ats_score,
            skill_match_score=ats_breakdown["skill_match_score"] / 100.0,
            experience_match_score=ats_breakdown["experience_match_score"] / 100.0,
            education_match_score=ats_breakdown["education_match_score"] / 100.0,
            domain_match_score=ats_breakdown.get("keyword_match_score", 0.0) / 100.0,
            industry_match_score=ats_breakdown.get("projects_score", 0.0) / 100.0,
            location_match_score=ats_breakdown.get("certifications_score", 0.0) / 100.0,
            salary_match_score=ats_breakdown.get("resume_quality_score", 0.0) / 100.0,
            availability_score=ats_breakdown.get("job_match", 0.0) / 100.0,
            ai_confidence_score=confidence_val,
            matching_skills=ats_breakdown["matched_skills"],
            missing_skills=ats_breakdown["missing_skills"],
            extra_skills=ats_breakdown["extra_skills"],
            analysis_data={
                "ats_breakdown": ats_breakdown,
                "ai_insights": ai_insights,
                "quality_analysis": quality_res,
                "duplicate_info": dup_res,
                "score_breakdown": ats_breakdown.get("score_breakdown", {}),
                "recommendations": ats_breakdown.get("recommendations", []),
                "parsing_confidence": confidence_val,
            },
            recommendation=ai_insights["hiring_recommendation"],
            computed_by=uploaded_by,
        )
        await self.repo.create_match_score(match_score_obj)

        # 12. Build structured response
        return CandidateScreeningResponse(
            candidate_id=str(candidate.id),
            application_id=None,
            resume_document_id=str(resume_doc.id),
            job_id=str(job_id) if job_id else None,
            status="COMPLETED",
            ats_score=ats_score,
            rank=1,
            match_tier=match_tier,
            parsing_confidence=confidence_val,
            candidate_details=ParsedResumeSchema.model_validate(parsed_clean),
            ats_breakdown=ATSScoreBreakdownSchema.model_validate(ats_breakdown),
            ai_insights=AIInsightsSchema.model_validate(ai_insights),
            quality_analysis=QualityAnalysisSchema.model_validate(quality_res),
            duplicate_info=DuplicateDetectionSchema.model_validate(dup_res),
            created_at=resume_doc.created_at,
        )

    async def parse_resume_direct(
        self,
        raw_text: str,
        job_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Parse raw resume text directly (dry-run / direct API)."""
        parsed_raw = await self.parser_service.parse_resume(raw_text)
        parsed_clean = self.cleaner_service.clean_parsed_data(parsed_raw, raw_text=raw_text)

        quality_res = self.quality_service.analyze_quality(
            raw_text=raw_text,
            parsed_data=parsed_clean,
            ocr_engine="direct_text",
        )

        job_data = {"title": "Target Role", "job_description": "", "min_experience": 0.0, "skills": []}
        if job_id:
            job_obj = await self.repo.get_job_by_id(job_id)
            if job_obj:
                job_skills = [getattr(s, "skill_name", getattr(s, "name", "")) for s in (job_obj.skills or [])]
                job_data = {
                    "title": job_obj.title,
                    "job_description": job_obj.job_description or "",
                    "min_experience": float(job_obj.min_experience or 0),
                    "skills": job_skills,
                }

        ats_breakdown = self.ats_service.calculate_ats_score(
            candidate_data=parsed_clean,
            job_data=job_data,
            formatting_score=quality_res["formatting_score"],
        )

        ai_insights = self.ranking_service.generate_ai_insights(
            candidate_name=parsed_clean.get("candidate_name") or "Candidate",
            ats_score=ats_breakdown["overall_ats_score"],
            ats_breakdown=ats_breakdown,
            parsed_data=parsed_clean,
            job_title=job_data["title"],
        )

        confidence_val = float(parsed_raw.get("parsing_confidence") or 0.95)

        return {
            "candidate": parsed_clean,
            "skills": parsed_clean.get("skills", []),
            "technical_skills": parsed_clean.get("technical_skills", []),
            "soft_skills": parsed_clean.get("soft_skills", []),
            "experience": parsed_clean.get("work_history", []),
            "education": parsed_clean.get("education", []),
            "ats_breakdown": ats_breakdown,
            "ai_insights": ai_insights,
            "quality_analysis": quality_res,
            "parsing_confidence": confidence_val,
        }

    async def match_candidate_for_job(
        self, candidate_id: uuid.UUID, job_id: uuid.UUID
    ) -> dict[str, Any]:
        """Match a specific candidate against a specific job and return match breakdown."""
        job = await self.repo.get_job_by_id(job_id)
        if not job:
            raise AppException(
                message=f"Job with ID '{job_id}' not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        cand = await self.repo.get_candidate_by_id(candidate_id)
        if not cand:
            raise AppException(
                message=f"Candidate with ID '{candidate_id}' not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        resume = await self.repo.get_latest_resume_doc(candidate_id)
        parsed_data = resume.parsed_data if resume and resume.parsed_data else {
            "candidate_name": f"{cand.first_name} {cand.last_name}".strip(),
            "email": cand.email,
            "phone": cand.phone,
            "skills": cand.skills or [],
            "total_experience_years": float(cand.years_experience or 0),
            "current_designation": cand.current_role or "",
            "education": [],
            "summary": cand.summary or "",
        }

        job_skills = [getattr(s, "skill_name", getattr(s, "name", "")) for s in (job.skills or [])]
        job_data = {
            "title": job.title,
            "job_description": job.job_description or "",
            "min_experience": float(job.min_experience or 0),
            "skills": job_skills,
        }

        ats_res = self.ats_service.calculate_ats_score(
            candidate_data=parsed_data,
            job_data=job_data,
        )

        cand_name = parsed_data.get("candidate_name") or f"{cand.first_name} {cand.last_name}".strip()
        ai_insights = self.ranking_service.generate_ai_insights(
            candidate_name=cand_name,
            ats_score=ats_res["overall_ats_score"],
            ats_breakdown=ats_res,
            parsed_data=parsed_data,
            job_title=job.title,
        )

        return {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "job_title": job.title,
            "overall_match_score": ats_res["overall_ats_score"],
            "skill_match_score": ats_res["skill_match_score"],
            "experience_match_score": ats_res["experience_match_score"],
            "education_match_score": ats_res["education_match_score"],
            "location_match_score": ats_res.get("certifications_score", 0.0),
            "matched_skills": ats_res["matched_skills"],
            "missing_required_skills": ats_res["missing_skills"],
            "extra_skills": ats_res["extra_skills"],
            "recommendation": ai_insights.get("hiring_recommendation") or "Good Match",
            "ai_insights": ai_insights,
        }

    async def get_candidate_profile_full(self, candidate_id: uuid.UUID) -> dict[str, Any]:
        """Fetch complete candidate profile details."""
        cand = await self.repo.get_candidate_by_id(candidate_id)
        if not cand:
            raise AppException(
                message=f"Candidate with ID '{candidate_id}' not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        resume = await self.repo.get_latest_resume_doc(candidate_id)
        parsed_data = resume.parsed_data if resume and resume.parsed_data else {}
        match_score = await self.repo.get_match_score(resume.id) if resume else None

        ats_breakdown = None
        ai_insights = None
        quality_res = None

        if match_score and match_score.analysis_data:
            analysis = match_score.analysis_data
            ats_breakdown = analysis.get("ats_breakdown")
            ai_insights = analysis.get("ai_insights")
            quality_res = analysis.get("quality_analysis")

        name = f"{cand.first_name} {cand.last_name}".strip()
        if not parsed_data.get("candidate_name"):
            parsed_data["candidate_name"] = name
        if not parsed_data.get("email"):
            parsed_data["email"] = cand.email
        if not parsed_data.get("phone"):
            parsed_data["phone"] = cand.phone

        return {
            "candidate_id": cand.id,
            "resume_document_id": resume.id if resume else None,
            "application_id": None,
            "job_id": match_score.job_id if match_score else None,
            "candidate_details": ParsedResumeSchema.model_validate(parsed_data),
            "ats_breakdown": ATSScoreBreakdownSchema.model_validate(ats_breakdown) if ats_breakdown else None,
            "ai_insights": AIInsightsSchema.model_validate(ai_insights) if ai_insights else None,
            "quality_analysis": QualityAnalysisSchema.model_validate(quality_res) if quality_res else None,
            "raw_text": resume.raw_text if resume else None,
            "resume_preview_url": resume.file_path if resume else None,
            "status": resume.parse_status if resume else "COMPLETED",
            "created_at": cand.created_at,
            "updated_at": cand.updated_at,
        }

    async def get_candidate_ats_analysis(self, candidate_id: uuid.UUID) -> dict[str, Any]:
        """Fetch detailed ATS score breakdown and insights for candidate."""
        profile = await self.get_candidate_profile_full(candidate_id)
        ats_breakdown = profile.get("ats_breakdown")
        ai_insights = profile.get("ai_insights")

        if not ats_breakdown:
            # Dynamic recalculation instead of hardcoded fallback
            ats_breakdown, ai_insights = await self._recalculate_ats_for_candidate(candidate_id)

        if not ai_insights:
            cand = await self.repo.get_candidate_by_id(candidate_id)
            cand_name = f"{cand.first_name} {cand.last_name}".strip() if cand else "Candidate"
            overall_val = ats_breakdown.overall_ats_score if hasattr(ats_breakdown, "overall_ats_score") else 50.0
            ai_insights = self.ranking_service.generate_ai_insights(
                candidate_name=cand_name,
                ats_score=overall_val,
                ats_breakdown={} if not hasattr(ats_breakdown, "model_dump") else ats_breakdown.model_dump(),
                parsed_data={},
                job_title="Target Role",
            )
            ai_insights = AIInsightsSchema.model_validate(ai_insights)

        overall = ats_breakdown.overall_ats_score if hasattr(ats_breakdown, "overall_ats_score") else 50.0
        match_tier = self.ranking_service.determine_match_tier(overall)

        return {
            "candidate_id": candidate_id,
            "job_id": profile.get("job_id"),
            "overall_ats_score": overall,
            "rank": 1,
            "match_tier": match_tier,
            "ats_breakdown": ats_breakdown,
            "ai_insights": ai_insights,
        }

    async def _recalculate_ats_for_candidate(
        self, candidate_id: uuid.UUID,
    ) -> tuple[ATSScoreBreakdownSchema, AIInsightsSchema | None]:
        """Dynamically recalculate ATS score for a candidate from resume + job data."""
        cand = await self.repo.get_candidate_by_id(candidate_id)
        resume = await self.repo.get_latest_resume_doc(candidate_id) if cand else None
        parsed_data = resume.parsed_data if resume and resume.parsed_data else {}

        # Build candidate data from parsed resume or candidate profile
        candidate_data = {
            "candidate_name": parsed_data.get("candidate_name") or (f"{cand.first_name} {cand.last_name}".strip() if cand else ""),
            "email": parsed_data.get("email") or (cand.email if cand else ""),
            "phone": parsed_data.get("phone") or (cand.phone if cand else ""),
            "skills": parsed_data.get("skills") or (cand.skills if cand and cand.skills else []),
            "total_experience_years": parsed_data.get("total_experience_years") or (float(cand.years_experience) if cand else 0.0),
            "current_designation": parsed_data.get("current_designation") or (cand.current_role if cand else ""),
            "education": parsed_data.get("education") or [],
            "projects": parsed_data.get("projects") or [],
            "certifications": parsed_data.get("certifications") or [],
            "summary": parsed_data.get("summary") or (cand.summary if cand else ""),
            "raw_text": resume.raw_text if resume else "",
        }

        # Find associated job from applications
        job_data = {"title": "Target Role", "job_description": "", "min_experience": 0.0, "skills": []}
        if cand and cand.applications:
            from sqlalchemy.orm import selectinload
            from sqlalchemy import select
            from app.models.recruitment import Application, Job
            app_res = await self.session.execute(
                select(Application)
                .options(selectinload(Application.job).selectinload(Job.skills))
                .where(Application.candidate_id == candidate_id)
                .order_by(Application.created_at.desc())
                .limit(1)
            )
            latest_app = app_res.scalar_one_or_none()
            if latest_app and latest_app.job:
                job_obj = latest_app.job
                job_skills = [s.skill_name for s in job_obj.skills] if job_obj.skills else []
                job_data = {
                    "title": job_obj.title,
                    "job_description": job_obj.job_description or "",
                    "min_experience": float(getattr(job_obj, "min_experience", 0) or 0),
                    "skills": job_skills,
                }

        ats_result = self.ats_service.calculate_ats_score(
            candidate_data=candidate_data,
            job_data=job_data,
        )

        # Map to ATSScoreBreakdownSchema
        ats_breakdown = ATSScoreBreakdownSchema(
            overall_ats_score=ats_result["overall_ats_score"],
            skill_match_score=ats_result["skill_match_score"],
            experience_match_score=ats_result["experience_match_score"],
            education_match_score=ats_result["education_match_score"],
            keyword_match_score=ats_result["keyword_match_score"],
            role_match_score=ats_result.get("job_match", 0.0),
            industry_match_score=ats_result.get("projects_score", 0.0),
            location_match_score=ats_result.get("certifications_score", 0.0),
            certification_match_score=ats_result.get("certifications_score", 0.0),
            resume_completeness=ats_result.get("resume_quality_score", 0.0),
            formatting_quality=ats_result.get("resume_quality_score", 0.0),
            matched_skills=ats_result["matched_skills"],
            missing_skills=ats_result["missing_skills"],
            extra_skills=ats_result["extra_skills"],
        )

        cand_name = candidate_data.get("candidate_name") or "Candidate"
        ai_insights_dict = self.ranking_service.generate_ai_insights(
            candidate_name=cand_name,
            ats_score=ats_result["overall_ats_score"],
            ats_breakdown=ats_result,
            parsed_data=candidate_data,
            job_title=job_data["title"],
        )
        ai_insights = AIInsightsSchema.model_validate(ai_insights_dict)

        return ats_breakdown, ai_insights

    async def match_job_candidates(self, job_id: uuid.UUID) -> dict[str, Any]:
        """Recalculate ATS scores and rankings for all candidates against the specified job."""
        job = await self.repo.get_job_by_id(job_id)
        if not job:
            raise AppException(
                message=f"Job with ID '{job_id}' not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        candidates, total = await self.repo.list_candidates(limit=100)
        matched_results = []
        total_scores = []

        job_skills = []
        if hasattr(job, "skills") and job.skills:
            job_skills = [getattr(s, "skill_name", getattr(s, "name", "")) for s in job.skills if getattr(s, "skill_name", getattr(s, "name", None))]

        job_data = {
            "title": job.title,
            "job_description": getattr(job, "job_description", "") or "",
            "min_experience": getattr(job, "min_experience", 0.0) or 0.0,
            "skills": job_skills,
        }

        for cand_dict in candidates:
            cand_id = cand_dict["candidate_id"]
            resume = await self.repo.get_latest_resume_doc(cand_id)
            if not resume or not resume.parsed_data:
                continue

            ats_res = self.ats_service.calculate_ats_score(
                candidate_data=resume.parsed_data,
                job_data=job_data,
            )
            score = ats_res["overall_ats_score"]
            total_scores.append(score)

            matched_results.append({
                "candidate_id": str(cand_id),
                "name": cand_dict["name"],
                "email": cand_dict["email"],
                "ats_score": score,
                "match_tier": self.ranking_service.determine_match_tier(score),
                "matched_skills": ats_res["matched_skills"],
                "missing_skills": ats_res["missing_skills"],
            })

        # Sort candidates by ATS score descending
        matched_results.sort(key=lambda x: x["ats_score"], reverse=True)
        for idx, item in enumerate(matched_results, start=1):
            item["rank"] = idx

        avg_score = round(sum(total_scores) / len(total_scores), 1) if total_scores else 0.0

        return {
            "job_id": job_id,
            "total_candidates_matched": len(matched_results),
            "top_matched_candidates": matched_results[:10],
            "average_ats_score": avg_score,
            "message": "ATS scores recalculated and rankings updated successfully for all candidates against job description.",
        }
