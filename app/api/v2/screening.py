"""AI Screening API v2 — Auto-screen candidates with SHORTLIST/REVIEW/REJECT decisions."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.screening_agent import ScreeningAgent
from app.core.config import settings
from app.core.rbac import require_admin_or_manager
from app.db.database import AsyncSessionLocal, get_db_session
from app.llm.client import get_llm_client
from app.middleware.auth import get_current_user_claims
from app.models.ai_recruitment import (
    AIResumeDocument,
    AIScreeningResult,
    CandidateMatchScore,
    RecruitmentAuditLog,
)
from app.models.recruitment import Application, ApplicationDocument, Job
from app.schemas.auth import APIResponse
from app.services.recruitment_service import RecruitmentService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/screening",
    tags=["AI Screening Agent v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class ScreenRequest(BaseModel):
    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    model: str | None = None
    auto_apply_decision: bool = Field(
        False,
        description="Auto-update application status based on screening decision",
    )


class BatchScreenRequest(BaseModel):
    job_id: uuid.UUID
    resume_document_ids: list[uuid.UUID] = Field(..., max_length=100)
    model: str | None = None
    auto_apply_decisions: bool = False


class JobScreenRunRequest(BaseModel):
    application_ids: list[uuid.UUID] | None = Field(
        None,
        description="Optional list of application UUIDs to screen (max 100). Defaults to all job applications.",
    )
    model: str | None = None


class ScreeningDecisionRequest(BaseModel):
    action: str = Field(..., description="SHORTLIST | REJECT | KEEP_REVIEW")
    reason: str | None = Field(None, description="Reason for decision (mandatory for REJECT)")


# ---------------------------------------------------------------------------
# Tenant Helpers
# ---------------------------------------------------------------------------

def _get_company_id(claims: dict | None) -> uuid.UUID:
    """Extract and validate tenant company_id from claims. Raises 401/403 if invalid."""
    if not claims or not isinstance(claims, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    raw = claims.get("company_id")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context missing in authentication claims",
        )
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid company ID in token",
        )


def _get_user_id(claims: dict | None) -> uuid.UUID | None:
    """Extract user_id from sub in claims."""
    if not claims or not isinstance(claims, dict):
        return None
    sub = claims.get("sub")
    try:
        return uuid.UUID(str(sub)) if sub else None
    except (ValueError, TypeError):
        return None


def _get_thresholds() -> dict[str, float]:
    """Return backend-only screening thresholds for frontend consumption."""
    return {
        "shortlist": float(settings.AI_SCREENING_THRESHOLD),
        "reject": float(settings.AI_REJECTION_THRESHOLD),
    }


def _get_recruitment_service(db: AsyncSession) -> RecruitmentService:
    """Helper to instantiate RecruitmentService with all required dependencies."""
    from app.repositories.recruitment_repository import RecruitmentRepository
    from app.repositories.auth_repository import AuthRepository
    from app.repositories.employee_repository import EmployeeRepository
    from app.services.email_service import EmailService

    return RecruitmentService(
        session=db,
        repo=RecruitmentRepository(db),
        auth_repo=AuthRepository(db),
        employee_repo=EmployeeRepository(db),
        email_service=EmailService(),
    )


async def _get_or_compute_match_score(
    db: AsyncSession,
    doc: AIResumeDocument,
    job: Job,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    model: str | None = None,
) -> float:
    """Fetch pre-computed CandidateMatchScore or compute it via CandidateMatcherAgent."""
    # 1. Check for existing score scoped by company
    score_res = await db.execute(
        select(CandidateMatchScore)
        .where(
            CandidateMatchScore.resume_document_id == doc.id,
            CandidateMatchScore.job_id == job.id,
            CandidateMatchScore.company_id == company_id,
        )
        .order_by(CandidateMatchScore.created_at.desc())
        .limit(1)
    )
    score_rec = score_res.scalar_one_or_none()
    if score_rec:
        return float(score_rec.overall_match_score)

    # 2. Compute via existing candidate matcher agent
    try:
        from app.agents.candidate_matcher import CandidateMatcherAgent

        parsed = doc.parsed_data or {}
        resume_text = doc.raw_text or ""
        if not resume_text and parsed:
            parts = [parsed.get("summary") or "", parsed.get("name") or ""]
            for exp in (parsed.get("experience") or []):
                parts.append(f"{exp.get('designation', '')} at {exp.get('company', '')}")
            resume_text = " ".join(p for p in parts if p)

        jd_text = job.job_description or ""
        if job.requirements:
            jd_text += "\n\nRequirements:\n" + job.requirements
        if job.responsibilities:
            jd_text += "\n\nResponsibilities:\n" + job.responsibilities

        matcher = CandidateMatcherAgent(llm_client=get_llm_client())
        match_result = await matcher.match(
            resume_text=resume_text,
            jd_text=jd_text,
            model=model,
            candidate_metadata={
                "expected_salary": parsed.get("expected_salary"),
                "notice_period": parsed.get("notice_period"),
                "location": parsed.get("address"),
            },
        )

        new_score = CandidateMatchScore(
            company_id=company_id,
            resume_document_id=doc.id,
            job_id=job.id,
            candidate_id=doc.candidate_id,
            overall_match_score=match_result.overall_match_score,
            skill_match_score=match_result.skill_match_score,
            experience_match_score=match_result.experience_match_score,
            education_match_score=match_result.education_match_score,
            domain_match_score=match_result.domain_match_score,
            industry_match_score=match_result.industry_match_score,
            location_match_score=match_result.location_match_score,
            salary_match_score=match_result.salary_match_score,
            availability_score=match_result.availability_score,
            ai_confidence_score=match_result.ai_confidence_score,
            matching_skills=match_result.matching_skills,
            missing_skills=match_result.missing_skills,
            extra_skills=match_result.extra_skills,
            analysis_data=match_result.to_dict(),
            recommendation=match_result.recommendation,
            model_used=model,
            computed_by=user_id,
        )
        db.add(new_score)
        await db.flush()
        return float(new_score.overall_match_score)
    except Exception as exc:
        logger.error(
            "Failed computing match score for resume %s and job %s: %s",
            doc.id,
            job.id,
            exc,
        )
        raise RuntimeError(f"Candidate match score computation failed: {str(exc)}") from exc


# ---------------------------------------------------------------------------
# Background Task for Screening Job
# ---------------------------------------------------------------------------

async def _execute_screening_run(
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    company_id: uuid.UUID,
    application_ids: list[uuid.UUID],
    model: str | None = None,
) -> None:
    """Execute asynchronous screening run for multiple applications."""
    logger.info(
        "Starting background screening run %s for job %s (total: %d apps)",
        run_id,
        job_id,
        len(application_ids),
    )
    async with AsyncSessionLocal() as session:
        try:
            # 1. Fetch job
            job_res = await session.execute(
                select(Job).where(
                    Job.id == job_id,
                    Job.company_id == company_id,
                    Job.is_deleted == False,
                )
            )
            job = job_res.scalar_one_or_none()
            if not job:
                logger.error("Background screening run %s: Job %s not found", run_id, job_id)
                return

            jd_text = (job.job_description or "") + "\n" + (job.requirements or "")
            agent = ScreeningAgent(llm_client=get_llm_client())

            for app_id in application_ids:
                # Load application
                app_res = await session.execute(
                    select(Application).where(
                        Application.id == app_id,
                        Application.company_id == company_id,
                    )
                )
                app = app_res.scalar_one_or_none()
                if not app:
                    continue

                # Locate resume document
                doc_res = await session.execute(
                    select(AIResumeDocument).where(
                        AIResumeDocument.application_id == app.id,
                        AIResumeDocument.company_id == company_id,
                    ).order_by(AIResumeDocument.created_at.desc()).limit(1)
                )
                doc = doc_res.scalar_one_or_none()

                # If not found directly, check application_documents
                if not doc:
                    app_doc_res = await session.execute(
                        select(ApplicationDocument).where(
                            ApplicationDocument.application_id == app.id,
                            ApplicationDocument.document_type == "RESUME",
                        ).order_by(ApplicationDocument.uploaded_at.desc()).limit(1)
                    )
                    app_doc = app_doc_res.scalar_one_or_none()
                    if app_doc:
                        # Try to link to AIResumeDocument by file_path
                        doc_res2 = await session.execute(
                            select(AIResumeDocument).where(
                                AIResumeDocument.file_path == app_doc.file_path,
                                AIResumeDocument.company_id == company_id,
                            ).limit(1)
                        )
                        doc = doc_res2.scalar_one_or_none()

                candidate_name = f"{app.first_name} {app.last_name}".strip()

                if not doc or doc.parse_status != "COMPLETED":
                    # Mark result as FAILED
                    failed_rec = AIScreeningResult(
                        company_id=company_id,
                        application_id=app.id,
                        resume_document_id=doc.id if doc else None,
                        job_id=job.id,
                        status="FAILED",
                        decision=None,
                        confidence=0.0,
                        match_score=0.0,
                        error_message="Resume document missing or parsing incomplete",
                        run_id=run_id,
                        model_used=model,
                        prompt_version="v2.0-compliance",
                        thresholds_used=_get_thresholds(),
                    )
                    session.add(failed_rec)
                    await session.commit()
                    continue

                # Get or compute match score
                match_score = 0.0
                try:
                    match_score = await _get_or_compute_match_score(
                        db=session,
                        doc=doc,
                        job=job,
                        company_id=company_id,
                        model=model,
                    )
                except Exception as score_exc:
                    logger.warning("Match score failed for application %s: %s", app.id, score_exc)
                    failed_rec = AIScreeningResult(
                        company_id=company_id,
                        application_id=app.id,
                        resume_document_id=doc.id,
                        job_id=job.id,
                        status="FAILED",
                        decision=None,
                        confidence=0.0,
                        match_score=0.0,
                        error_message=f"Match score computation failed: {str(score_exc)}",
                        run_id=run_id,
                        model_used=model,
                        prompt_version="v2.0-compliance",
                        thresholds_used=_get_thresholds(),
                    )
                    session.add(failed_rec)
                    await session.commit()
                    continue

                # Run screening agent
                resume_text = doc.raw_text or ""
                if not resume_text:
                    parsed = doc.parsed_data or {}
                    resume_text = " ".join(filter(None, [
                        parsed.get("summary", ""),
                        parsed.get("name", ""),
                        " ".join(parsed.get("skills", {}).get("programming_languages", [])),
                    ]))

                screen_res = await agent.screen(
                    resume_text=resume_text,
                    jd_text=jd_text,
                    match_score=match_score,
                    model=model,
                    candidate_name=candidate_name,
                )

                screening_rec = AIScreeningResult(
                    company_id=company_id,
                    application_id=app.id,
                    resume_document_id=doc.id,
                    job_id=job.id,
                    status=screen_res.status,
                    decision=screen_res.decision,
                    confidence=screen_res.confidence,
                    match_score=match_score,
                    auto_action_taken=screen_res.auto_shortlisted or screen_res.auto_rejected,
                    model_used=screen_res.model_used,
                    prompt_version=screen_res.prompt_version,
                    thresholds_used=screen_res.thresholds_used,
                    input_hash=screen_res.input_hash,
                    error_message=screen_res.error_message,
                    strengths=screen_res.strengths,
                    weaknesses=screen_res.weaknesses,
                    missing_skills=screen_res.missing_skills,
                    risk_analysis=screen_res.risk_analysis,
                    red_flags=screen_res.red_flags,
                    green_flags=screen_res.green_flags,
                    hiring_recommendation=screen_res.hiring_recommendation,
                    hr_notes=screen_res.hr_notes,
                    questions_to_ask=screen_res.questions_to_ask,
                    run_id=run_id,
                )
                session.add(screening_rec)
                await session.commit()

            logger.info("Background screening run %s completed successfully", run_id)
        except Exception as exc:
            logger.exception("Unexpected error during screening run %s: %s", run_id, exc)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/screen",
    response_model=APIResponse[dict],
    summary="AI-screen a single candidate",
)
async def screen_candidate(
    body: ScreenRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Screen a single candidate and return detailed analysis with tenant isolation."""
    company_id = _get_company_id(claims)
    user_id = _get_user_id(claims)

    # 1. Load and verify resume document scoped to company
    doc_res = await db.execute(
        select(AIResumeDocument).where(
            AIResumeDocument.id == body.resume_document_id,
            AIResumeDocument.company_id == company_id,
        )
    )
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume document not found",
        )
    if doc.parse_status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Resume not yet parsed",
        )

    # 2. Load and verify job scoped to company
    job_res = await db.execute(
        select(Job).where(
            Job.id == body.job_id,
            Job.company_id == company_id,
            Job.is_deleted == False,
        )
    )
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # 3. Pre-computed match score or compute via candidate matching service
    try:
        match_score = await _get_or_compute_match_score(
            db=db,
            doc=doc,
            job=job,
            company_id=company_id,
            user_id=user_id,
            model=body.model,
        )
    except Exception as score_exc:
        # Step 2: If candidate match computation fails, return status FAILED with clear error
        failed_rec = AIScreeningResult(
            company_id=company_id,
            application_id=doc.application_id,  # nullable, never a fake UUID
            resume_document_id=body.resume_document_id,
            job_id=body.job_id,
            status="FAILED",
            decision=None,
            confidence=0.0,
            match_score=0.0,
            error_message=f"Candidate match score computation failed: {str(score_exc)}",
            model_used=body.model,
            prompt_version="v2.0-compliance",
            thresholds_used=_get_thresholds(),
        )
        db.add(failed_rec)
        await db.commit()

        return APIResponse[dict](
            success=False,
            message=f"Screening failed: Match score computation error: {str(score_exc)}",
            data={
                "screening_id": str(failed_rec.id),
                "status": "FAILED",
                "decision": None,
                "error": str(score_exc),
                "thresholds": _get_thresholds(),
            },
            errors=[str(score_exc)],
        )

    # 4. Build text representations
    resume_text = doc.raw_text or ""
    if not resume_text:
        parsed = doc.parsed_data or {}
        resume_text = " ".join(filter(None, [
            parsed.get("summary", ""),
            parsed.get("name", ""),
            " ".join(parsed.get("skills", {}).get("programming_languages", [])),
        ]))

    jd_text = (job.job_description or "") + "\n" + (job.requirements or "")

    # 5. Run screening agent (bias stripping, head+tail truncation, retries, timeout)
    agent = ScreeningAgent(llm_client=get_llm_client())
    result = await agent.screen(
        resume_text=resume_text,
        jd_text=jd_text,
        match_score=match_score,
        model=body.model,
        candidate_name=doc.candidate_name,
    )

    # 6. Store screening result — never use a fake UUID for application_id
    screening_rec = AIScreeningResult(
        company_id=company_id,
        application_id=doc.application_id,  # Nullable in DB; no fake uuid
        resume_document_id=body.resume_document_id,
        job_id=body.job_id,
        status=result.status,
        decision=result.decision,
        confidence=result.confidence,
        match_score=match_score,
        auto_action_taken=result.auto_shortlisted or result.auto_rejected,
        model_used=result.model_used,
        prompt_version=result.prompt_version,
        thresholds_used=result.thresholds_used,
        input_hash=result.input_hash,
        error_message=result.error_message,
        strengths=result.strengths,
        weaknesses=result.weaknesses,
        missing_skills=result.missing_skills,
        risk_analysis=result.risk_analysis,
        red_flags=result.red_flags,
        green_flags=result.green_flags,
        hiring_recommendation=result.hiring_recommendation,
        hr_notes=result.hr_notes,
        questions_to_ask=result.questions_to_ask,
    )
    db.add(screening_rec)

    # 7. Auto-apply decision if requested, application exists, and compliance rules satisfied
    if body.auto_apply_decision and doc.application_id and result.status == "COMPLETED":
        rec_service = _get_recruitment_service(db)
        if result.auto_shortlisted:
            await rec_service.update_application_status(doc.application_id, "SHORTLISTED")
            logger.info("Auto-shortlisted application %s", doc.application_id)
        elif result.auto_rejected and getattr(settings, "AI_AUTO_REJECT_ENABLED", False):
            await rec_service.update_application_status(doc.application_id, "REJECTED")
            logger.info("Auto-rejected application %s", doc.application_id)

    await db.commit()

    return APIResponse[dict](
        success=(result.status == "COMPLETED"),
        message=f"Screening complete. Decision: {result.decision or 'FAILED'}",
        data={
            "screening_id": str(screening_rec.id),
            "resume_document_id": str(body.resume_document_id),
            "job_id": str(body.job_id),
            "match_score_used": match_score,
            "thresholds": _get_thresholds(),
            **result.to_dict(),
        },
        errors=[result.error_message] if result.error_message else None,
    )


@router.post(
    "/batch-screen",
    response_model=APIResponse[dict],
    summary="Batch screen multiple candidates for a job",
)
async def batch_screen_candidates(
    body: BatchScreenRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Screen multiple candidates concurrently with tenant scoping, persistence, and per-item fault tolerance."""
    company_id = _get_company_id(claims)

    job_res = await db.execute(
        select(Job).where(
            Job.id == body.job_id,
            Job.company_id == company_id,
            Job.is_deleted == False,
        )
    )
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    jd_text = (job.job_description or "") + "\n" + (job.requirements or "")

    docs_res = await db.execute(
        select(AIResumeDocument).where(
            AIResumeDocument.id.in_(body.resume_document_ids),
            AIResumeDocument.company_id == company_id,
            AIResumeDocument.parse_status == "COMPLETED",
        )
    )
    docs = docs_res.scalars().all()

    if not docs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No completed resumes found for this tenant",
        )

    agent = ScreeningAgent(llm_client=get_llm_client())
    rec_service = _get_recruitment_service(db)
    output = []
    shortlisted, rejected, review, failed = 0, 0, 0, 0

    for doc in docs:
        try:
            # Match score computation with fallback handling
            try:
                match_score = await _get_or_compute_match_score(
                    db=db,
                    doc=doc,
                    job=job,
                    company_id=company_id,
                    model=body.model,
                )
            except Exception as match_exc:
                logger.warning("Match score failed for resume %s: %s", doc.id, match_exc)
                match_score = 0.0
                failed += 1
                failed_rec = AIScreeningResult(
                    company_id=company_id,
                    application_id=doc.application_id,
                    resume_document_id=doc.id,
                    job_id=body.job_id,
                    status="FAILED",
                    decision=None,
                    confidence=0.0,
                    match_score=0.0,
                    error_message=f"Match score calculation failed: {str(match_exc)}",
                    model_used=body.model,
                    prompt_version="v2.0-compliance",
                    thresholds_used=_get_thresholds(),
                )
                db.add(failed_rec)
                output.append({
                    "resume_document_id": str(doc.id),
                    "candidate_name": doc.candidate_name,
                    "status": "FAILED",
                    "decision": None,
                    "confidence": 0.0,
                    "error": str(match_exc),
                })
                continue

            resume_text = doc.raw_text or ""
            if not resume_text:
                parsed = doc.parsed_data or {}
                resume_text = " ".join(filter(None, [
                    parsed.get("summary", ""),
                    parsed.get("name", ""),
                    " ".join(parsed.get("skills", {}).get("programming_languages", [])),
                ]))

            result = await agent.screen(
                resume_text=resume_text,
                jd_text=jd_text,
                match_score=match_score,
                model=body.model,
                candidate_name=doc.candidate_name,
            )

            # Persist AIScreeningResult row
            screening_rec = AIScreeningResult(
                company_id=company_id,
                application_id=doc.application_id,
                resume_document_id=doc.id,
                job_id=body.job_id,
                status=result.status,
                decision=result.decision,
                confidence=result.confidence,
                match_score=match_score,
                auto_action_taken=result.auto_shortlisted or result.auto_rejected,
                model_used=result.model_used,
                prompt_version=result.prompt_version,
                thresholds_used=result.thresholds_used,
                input_hash=result.input_hash,
                error_message=result.error_message,
                strengths=result.strengths,
                weaknesses=result.weaknesses,
                missing_skills=result.missing_skills,
                risk_analysis=result.risk_analysis,
                red_flags=result.red_flags,
                green_flags=result.green_flags,
                hiring_recommendation=result.hiring_recommendation,
                hr_notes=result.hr_notes,
                questions_to_ask=result.questions_to_ask,
            )
            db.add(screening_rec)

            # Honor auto_apply_decisions
            if body.auto_apply_decisions and doc.application_id and result.status == "COMPLETED":
                if result.auto_shortlisted:
                    await rec_service.update_application_status(doc.application_id, "SHORTLISTED")
                elif result.auto_rejected and getattr(settings, "AI_AUTO_REJECT_ENABLED", False):
                    await rec_service.update_application_status(doc.application_id, "REJECTED")

            if result.status == "FAILED":
                failed += 1
            elif result.decision == "SHORTLIST":
                shortlisted += 1
            elif result.decision == "REJECT":
                rejected += 1
            else:
                review += 1

            output.append({
                "resume_document_id": str(doc.id),
                "candidate_name": doc.candidate_name,
                "status": result.status,
                "decision": result.decision,
                "confidence": round(result.confidence, 4),
                "auto_shortlisted": result.auto_shortlisted,
                "auto_rejected": result.auto_rejected,
                "hr_notes": result.hr_notes,
            })
        except Exception as item_exc:
            logger.exception("Item error during batch screening for doc %s: %s", doc.id, item_exc)
            failed += 1
            output.append({
                "resume_document_id": str(doc.id),
                "candidate_name": doc.candidate_name,
                "status": "FAILED",
                "decision": None,
                "confidence": 0.0,
                "error": str(item_exc),
            })

    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Batch screening complete: {shortlisted} shortlisted, {rejected} rejected, {review} for review, {failed} failed.",
        data={
            "job_id": str(body.job_id),
            "total": len(output),
            "shortlisted": shortlisted,
            "rejected": rejected,
            "review": review,
            "failed": failed,
            "thresholds": _get_thresholds(),
            "results": output,
        },
        errors=None,
    )


@router.post(
    "/jobs/{job_id}/run",
    response_model=APIResponse[dict],
    summary="Trigger bulk AI screening run for a job",
)
async def run_job_screening(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: JobScreenRunRequest | None = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Run AI screening as a background task across job applications."""
    company_id = _get_company_id(claims)

    job_res = await db.execute(
        select(Job).where(
            Job.id == job_id,
            Job.company_id == company_id,
            Job.is_deleted == False,
        )
    )
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Query candidate applications for this job
    app_stmt = select(Application.id).where(
        Application.job_id == job_id,
        Application.company_id == company_id,
    )
    if body and body.application_ids:
        app_stmt = app_stmt.where(Application.id.in_(body.application_ids[:100]))

    app_rows = (await db.execute(app_stmt)).scalars().all()
    application_ids = list(app_rows)
    total = len(application_ids)
    run_id = uuid.uuid4()

    # Schedule non-blocking execution via BackgroundTasks
    background_tasks.add_task(
        _execute_screening_run,
        run_id=run_id,
        job_id=job_id,
        company_id=company_id,
        application_ids=application_ids,
        model=body.model if body else None,
    )

    return APIResponse[dict](
        success=True,
        message="Job screening run initiated in background.",
        data={
            "run_id": str(run_id),
            "status": "RUNNING",
            "total": total,
            "thresholds": _get_thresholds(),
        },
        errors=None,
    )


@router.get(
    "/jobs/{job_id}/results",
    response_model=APIResponse[dict],
    summary="Get latest AI screening results per application for a job",
)
async def get_job_screening_results(
    job_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return the latest screening results per application for a job according to frontend contract."""
    company_id = _get_company_id(claims)

    job_res = await db.execute(
        select(Job).where(
            Job.id == job_id,
            Job.company_id == company_id,
            Job.is_deleted == False,
        )
    )
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Fetch all applications for this job
    apps_res = await db.execute(
        select(Application)
        .where(
            Application.job_id == job_id,
            Application.company_id == company_id,
        )
        .order_by(Application.created_at.desc())
    )
    applications = apps_res.scalars().all()

    # Fetch all screening results for this job and company
    results_res = await db.execute(
        select(AIScreeningResult)
        .where(
            AIScreeningResult.job_id == job_id,
            AIScreeningResult.company_id == company_id,
        )
        .order_by(AIScreeningResult.created_at.desc())
    )
    all_results = results_res.scalars().all()

    latest_by_app: dict[uuid.UUID, AIScreeningResult] = {}
    latest_run_id = None
    for r in all_results:
        if r.run_id and not latest_run_id:
            latest_run_id = r.run_id
        if r.application_id and r.application_id not in latest_by_app:
            latest_by_app[r.application_id] = r

    # Build results list matching the frontend contract
    results_list = []
    completed_count = 0

    for app in applications:
        r = latest_by_app.get(app.id)
        cand_name = f"{app.first_name} {app.last_name}".strip()
        if r:
            if r.status == "COMPLETED":
                completed_count += 1
            results_list.append({
                "application_id": str(app.id),
                "candidate_id": str(app.candidate_id) if app.candidate_id else None,
                "candidate_name": cand_name,
                "resume_document_id": str(r.resume_document_id) if r.resume_document_id else None,
                "status": r.status,
                "decision": r.decision,
                "confidence": r.confidence,
                "match_score": r.match_score if r.match_score is not None else 0.0,
                "strengths": r.strengths or [],
                "weaknesses": r.weaknesses or [],
                "missing_skills": r.missing_skills or [],
                "red_flags": r.red_flags or [],
                "green_flags": r.green_flags or [],
                "hiring_recommendation": r.hiring_recommendation,
                "hr_notes": r.hr_notes,
                "questions_to_ask": r.questions_to_ask or [],
                "model_used": r.model_used,
                "screened_at": r.created_at.isoformat() if r.created_at else None,
                "human_decision": r.human_decision,
                "human_decision_by": str(r.human_decision_by) if r.human_decision_by else None,
                "human_decision_reason": r.human_decision_reason,
            })
        else:
            results_list.append({
                "application_id": str(app.id),
                "candidate_id": str(app.candidate_id) if app.candidate_id else None,
                "candidate_name": cand_name,
                "resume_document_id": None,
                "status": "PENDING",
                "decision": None,
                "confidence": 0.0,
                "match_score": 0.0,
                "strengths": [],
                "weaknesses": [],
                "missing_skills": [],
                "red_flags": [],
                "green_flags": [],
                "hiring_recommendation": None,
                "hr_notes": None,
                "questions_to_ask": [],
                "model_used": None,
                "screened_at": None,
                "human_decision": None,
                "human_decision_by": None,
                "human_decision_reason": None,
            })

    total = len(applications)
    run_status = "COMPLETED" if (total > 0 and completed_count == total) else ("RUNNING" if completed_count > 0 else "PENDING")

    return APIResponse[dict](
        success=True,
        message=f"Retrieved screening results for {len(results_list)} application(s).",
        data={
            "thresholds": _get_thresholds(),
            "run": {
                "run_id": str(latest_run_id) if latest_run_id else None,
                "status": run_status,
                "completed": completed_count,
                "total": total,
            },
            "results": results_list,
        },
        errors=None,
    )


@router.post(
    "/results/{screening_id}/decision",
    response_model=APIResponse[dict],
    summary="Record human decision and update application workflow stage",
)
async def submit_human_decision(
    screening_id: uuid.UUID,
    body: ScreeningDecisionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Record human reviewer decision (SHORTLIST|REJECT|KEEP_REVIEW) and apply stage change."""
    company_id = _get_company_id(claims)
    user_id = _get_user_id(claims)

    valid_actions = {"SHORTLIST", "REJECT", "KEEP_REVIEW"}
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid action '{body.action}'. Must be one of: {', '.join(valid_actions)}",
        )

    if body.action == "REJECT" and not (body.reason and body.reason.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reason is mandatory when action is REJECT",
        )

    # 1. Fetch screening result with strict tenant check
    result_res = await db.execute(
        select(AIScreeningResult).where(
            AIScreeningResult.id == screening_id,
            AIScreeningResult.company_id == company_id,
        )
    )
    screening = result_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Screening result not found",
        )

    before_state = {
        "human_decision": screening.human_decision,
        "human_decision_by": str(screening.human_decision_by) if screening.human_decision_by else None,
        "human_decision_reason": screening.human_decision_reason,
    }

    # 2. Apply stage change through existing application stage service (one status vocabulary)
    if screening.application_id:
        status_vocabulary_map = {
            "SHORTLIST": "SHORTLISTED",
            "REJECT": "REJECTED",
            "KEEP_REVIEW": "UNDER_REVIEW",
        }
        target_stage = status_vocabulary_map[body.action]
        rec_service = _get_recruitment_service(db)
        await rec_service.update_application_status(screening.application_id, target_stage)

    # 3. Store human decision fields
    now_dt = datetime.now(timezone.utc)
    screening.human_decision = body.action
    screening.human_decision_by = user_id
    screening.human_decision_reason = body.reason
    screening.human_decision_at = now_dt

    # 4. Write audit log entry
    audit_entry = RecruitmentAuditLog(
        company_id=company_id,
        user_id=user_id,
        action="SCREENING_HUMAN_DECISION",
        entity_type="AIScreeningResult",
        entity_id=str(screening.id),
        before_state=before_state,
        after_state={
            "human_decision": body.action,
            "human_decision_reason": body.reason,
            "application_id": str(screening.application_id) if screening.application_id else None,
        },
        meta_data={
            "screening_id": str(screening.id),
            "job_id": str(screening.job_id),
            "action": body.action,
        },
    )
    db.add(audit_entry)
    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Human decision '{body.action}' recorded and application workflow stage updated.",
        data={
            "screening_id": str(screening.id),
            "action": body.action,
            "reason": body.reason,
            "human_decision_by": str(user_id) if user_id else None,
            "human_decision_at": now_dt.isoformat(),
            "thresholds": _get_thresholds(),
        },
        errors=None,
    )


@router.get(
    "/history/{application_id}",
    response_model=APIResponse[dict],
    summary="Get screening history for an application",
)
async def get_screening_history(
    application_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve all screening results for an application scoped to tenant."""
    company_id = _get_company_id(claims)

    # Validate application exists within tenant
    app_res = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.company_id == company_id,
        )
    )
    app = app_res.scalar_one_or_none()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    result = await db.execute(
        select(AIScreeningResult)
        .where(
            AIScreeningResult.application_id == application_id,
            AIScreeningResult.company_id == company_id,
        )
        .order_by(AIScreeningResult.created_at.desc())
    )
    records = result.scalars().all()

    return APIResponse[dict](
        success=True,
        message=f"Found {len(records)} screening record(s).",
        data={
            "application_id": str(application_id),
            "total": len(records),
            "thresholds": _get_thresholds(),
            "records": [
                {
                    "id": str(r.id),
                    "status": r.status,
                    "decision": r.decision,
                    "confidence": r.confidence,
                    "match_score": r.match_score,
                    "auto_action_taken": r.auto_action_taken,
                    "hiring_recommendation": r.hiring_recommendation,
                    "human_decision": r.human_decision,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ],
        },
        errors=None,
    )
