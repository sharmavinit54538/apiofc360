"""Recruitment Management service layer: business logic, rules, and files/email workflows."""

from __future__ import annotations

import logging
import math
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone, time
from typing import TYPE_CHECKING, Any

from fastapi import Depends, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.security import hash_password
from app.db.database import get_db_session
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.recruitment_repository import RecruitmentRepository
from app.schemas.recruitment import (
    ApplicationCreate,
    ApplicationListItem,
    ApplicationListResponse,
    ApplicationResponse,
    CompleteRoundRequest,
    InterviewResponse,
    InterviewScheduleCreate,
    JobCreate,
    JobListResponse,
    JobResponse,
    JobUpdate,
    OfferCreate,
    OfferResponse,
    RecruitmentDashboardStats,
    CandidateCreate,
    CandidateUpdate,
    CandidateResponse,
    JobRequisitionCreate,
    JobRequisitionUpdate,
    JobRequisitionResponse,
    RecruitmentVendorCreate,
    RecruitmentVendorUpdate,
    RecruitmentVendorResponse,
    ScorecardTemplateCreate,
    ScorecardTemplateResponse,
    ScorecardSubmissionCreate,
    ScorecardSubmissionResponse,
    CandidateCrmNoteCreate,
    CandidateCrmNoteResponse,
    CandidateReferralCreate,
    CandidateReferralResponse,
    RecruitmentAutomationRuleCreate,
    RecruitmentAutomationRuleResponse,
    RecruitmentNotificationResponse,
    RecruitmentRecentActivity,
)
from app.services.email_service import EmailService, get_email_service
from app.utils.employee import generate_temp_password

if TYPE_CHECKING:
    from app.models.recruitment import Job, Application

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
UPLOAD_DIR = os.path.join("uploads", "resumes")

# Make upload directory if not exists
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Slug Generator
# ---------------------------------------------------------------------------

async def generate_job_slug(title: str, repo: RecruitmentRepository) -> str:
    # URL safe slug
    base_slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", title.lower()).strip("-")
    base_slug = re.sub(r"-+", "-", base_slug)
    
    slug = base_slug
    for i in range(1, 100):
        existing = await repo.get_job_by_slug_raw(slug)
        if not existing:
            return slug
        slug = f"{base_slug}-{i}"
    return f"{base_slug}-{uuid.uuid4().hex[:6]}"


class RecruitmentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: RecruitmentRepository,
        auth_repo: AuthRepository,
        employee_repo: EmployeeRepository,
        email_service: EmailService,
    ) -> None:
        self.session = session
        self.repo = repo
        self.auth_repo = auth_repo
        self.employee_repo = employee_repo
        self.email_service = email_service

    # ------------------------------------------------------------------
    # Recruitment Dashboard Stats
    # ------------------------------------------------------------------

    async def get_dashboard_stats(self, company_id: uuid.UUID | None = None) -> RecruitmentDashboardStats:
        try:
            metrics = await self.repo.get_dashboard_metrics(company_id)
            return RecruitmentDashboardStats(**metrics)
        except SQLAlchemyError as exc:
            logger.exception("get_dashboard_stats: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Job Management (Admin/HR)
    # ------------------------------------------------------------------

    async def create_job(self, user_id: uuid.UUID, payload: JobCreate) -> JobResponse:
        logger.info("create_job | user_id=%s | title=%s", user_id, payload.title)
        try:
            slug = await generate_job_slug(payload.title, self.repo)
            
            job_data = payload.model_dump(exclude={"rounds", "skills"})
            job_data["slug"] = slug
            job_data["created_by"] = user_id

            job = await self.repo.create_job(**job_data)

            # Add required skills
            for s in payload.skills:
                await self.repo.add_job_skill(job.id, s)

            await self.session.commit()

            # Re-fetch full job details
            full_job = await self.repo.get_job_by_id(job.id)
            return JobResponse.model_validate(full_job)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_jobs(
        self,
        status: str | None,
        search: str | None,
        department: str | None,
        location: str | None,
        page: int,
        limit: int,
    ) -> JobListResponse:
        try:
            offset = (page - 1) * limit
            jobs = await self.repo.list_jobs(
                status=status,
                search=search,
                department=department,
                location=location,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_jobs(
                status=status,
                search=search,
                department=department,
                location=location,
            )
            items = [JobResponse.model_validate(j) for j in jobs]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return JobListResponse(items=items, total=total, page=page, limit=limit, pages=pages)
        except SQLAlchemyError as exc:
            logger.exception("list_jobs: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_job(self, job_uuid: uuid.UUID) -> JobResponse:
        try:
            job = await self.repo.get_job_by_id(job_uuid)
            if not job:
                raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)
            return JobResponse.model_validate(job)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_job(self, user_id: uuid.UUID, job_uuid: uuid.UUID, payload: JobUpdate) -> JobResponse:
        logger.info("update_job | user_id=%s | job_id=%s", user_id, job_uuid)
        try:
            job = await self.repo.get_job_by_id(job_uuid)
            if not job:
                raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)

            job_data = {k: v for k, v in payload.model_dump(exclude={"skills"}).items() if v is not None}
            if "title" in job_data and job_data["title"] != job.title:
                job_data["slug"] = await generate_job_slug(job_data["title"], self.repo)

            await self.repo.update_job(job_uuid, **job_data)

            if payload.skills is not None:
                await self.repo.clear_job_skills(job_uuid)
                for s in payload.skills:
                    await self.repo.add_job_skill(job_uuid, s)

            await self.session.commit()
            full_job = await self.repo.get_job_by_id(job_uuid)
            return JobResponse.model_validate(full_job)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_job(self, user_id: uuid.UUID, job_uuid: uuid.UUID) -> None:
        logger.info("delete_job | user_id=%s | job_id=%s", user_id, job_uuid)
        try:
            job = await self.repo.get_job_by_id(job_uuid)
            if not job:
                raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.soft_delete_job(job_uuid)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_job_status(self, job_uuid: uuid.UUID, new_status: str) -> JobResponse:
        try:
            job = await self.repo.get_job_by_id(job_uuid)
            if not job:
                raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.update_job(job_uuid, status=new_status.upper())
            await self.session.commit()
            full_job = await self.repo.get_job_by_id(job_uuid)
            return JobResponse.model_validate(full_job)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_job_status: db error", exc_info=exc)
    async def duplicate_job(self, user_id: uuid.UUID, job_uuid: uuid.UUID) -> JobResponse:
        try:
            job = await self.repo.get_job_by_id(job_uuid)
            if not job:
                raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            slug = await generate_job_slug(job.title + " Copy", self.repo)
            new_job = await self.repo.create_job(
                title=job.title + " (Copy)",
                slug=slug,
                department=job.department,
                designation=job.designation,
                employment_type=job.employment_type,
                experience_required=job.experience_required,
                min_experience=job.min_experience,
                max_experience=job.max_experience,
                min_salary=job.min_salary,
                max_salary=job.max_salary,
                location=job.location,
                vacancies=job.vacancies,
                job_description=job.job_description,
                responsibilities=job.responsibilities,
                requirements=job.requirements,
                benefits=job.benefits,
                interview_process_description=job.interview_process_description,
                status="DRAFT",
                created_by=user_id,
            )
            for skill in job.skills:
                await self.repo.add_job_skill(new_job.id, skill.skill_name)
            await self.session.commit()
            full_job = await self.repo.get_job_by_id(new_job.id)
            return JobResponse.model_validate(full_job)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("duplicate_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def generate_ai_job_description(
        self,
        title: str,
        department: str,
        employment_type: str,
        location: str,
        skills: list[str],
        experience: str | None = None,
    ) -> str:
        from app.services.ollama_client import ollama_client
        is_healthy = await ollama_client.check_health()
        if not is_healthy:
            raise AppException(message="Local Ollama AI service is currently unavailable.", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
            
        skills_str = ", ".join(skills) if skills else "relevant industry skills"
        prompt = f"""Generate a professional and comprehensive job description for the following position:
Role Title: {title}
Department: {department}
Employment Type: {employment_type}
Location: {location}
Required Skills: {skills_str}
Experience: {experience or 'not specified'}

Please structure the description using Markdown with these exact headings:
# Job Title
# About the Role
# Key Responsibilities
# Required Skills
# Preferred Skills
# Qualifications
# Experience (AI Suggested)
# Location
# Employment Type (AI Suggested)
# Salary (Optional Placeholder)
# Benefits
# Why Join Us
# Hiring Process

Generate realistic content under each heading. Make the tone professional, encouraging, and clear. Do not write any preamble or conversational intro/outro. Return ONLY the markdown job description."""

        system_prompt = "You are an expert technical recruiter and HR copywriter. Write a clean, well-formatted markdown job description."
        
        response = await ollama_client.generate_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            options={"num_predict": 1024, "temperature": 0.5}
        )
        if not response:
            raise AppException(message="AI failed to generate description. Please check local Ollama logs.", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return response

    # ------------------------------------------------------------------
    # Career Portal (Public Pages)
    # ------------------------------------------------------------------

    async def get_public_careers(self) -> list[JobResponse]:
        try:
            jobs = await self.repo.list_jobs(status="PUBLISHED", limit=100)
            return [JobResponse.model_validate(j) for j in jobs]
        except SQLAlchemyError as exc:
            logger.exception("get_public_careers: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_public_job_detail(self, slug: str) -> JobResponse:
        try:
            job = await self.repo.get_job_by_slug(slug)
            if not job:
                raise AppException(message="Job posting not found or not published.", status_code=status.HTTP_404_NOT_FOUND)
            return JobResponse.model_validate(job)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_public_job_detail: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def apply_to_job(self, slug: str, payload: ApplicationCreate, resume_file: UploadFile) -> ApplicationResponse:
        logger.info("apply_to_job | slug=%s | email=%s", slug, payload.email)
        try:
            job = await self.repo.get_job_by_slug(slug)
            if not job:
                raise AppException(message="Job posting not found or closed.", status_code=status.HTTP_404_NOT_FOUND)

            # Resume file validation
            filename = resume_file.filename or "resume.pdf"
            _, ext = os.path.splitext(filename.lower())
            if ext not in ALLOWED_EXTENSIONS:
                raise AppException(
                    message="Invalid file extension. Only PDF, DOC, and DOCX are allowed.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Check file size (Read chunks to verify size securely)
            file_size = 0
            file_data = await resume_file.read()
            file_size = len(file_data)
            await resume_file.seek(0)

            if file_size > MAX_FILE_SIZE_BYTES:
                raise AppException(
                    message="File size exceeds maximum limit of 5 MB.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Save resume securely on disk
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            save_path = os.path.join(UPLOAD_DIR, unique_filename)
            with open(save_path, "wb") as f:
                f.write(file_data)

            # Create or get Candidate record
            candidate = await self.repo.get_candidate_by_email(payload.email)
            if not candidate:
                candidate = await self.repo.create_candidate(
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    email=payload.email.lower().strip(),
                    phone=payload.phone,
                    location=f"{payload.city}, {payload.state}, {payload.country}",
                    years_experience=payload.experience_years,
                    current_company=payload.current_company,
                    current_role=payload.current_designation,
                    expected_salary=payload.expected_ctc,
                    resume_path=save_path,
                    resume_name=filename,
                    source="Career Site",
                    is_talent_pool=False,
                )
            else:
                candidate.resume_path = save_path
                candidate.resume_name = filename
                await self.session.flush()

            # Create application record
            app_data = payload.model_dump()
            app_data.pop("is_fresher", None)
            app_data["job_id"] = job.id
            app_data["company_id"] = job.company_id
            app_data["status"] = "APPLIED"
            app_data["candidate_id"] = candidate.id

            application = await self.repo.create_application(**app_data)

            # Save application document path
            doc_kwargs = {
                "application_id": application.id,
                "document_type": "RESUME",
                "file_path": save_path,
                "file_name": filename,
                "file_size": file_size,
            }
            await self.repo.add_application_document(**doc_kwargs)

            await self.session.commit()

            logger.info(
                "[ATS PIPELINE ENTRY CREATED] Candidate ID=%s | Application ID=%s | Job ID=%s | Company ID=%s | Stage=APPLIED",
                candidate.id,
                application.id,
                job.id,
                job.company_id,
            )

            import asyncio
            asyncio.create_task(
                self.screen_candidate_resume_task(
                    application_id=application.id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                    resume_path=save_path,
                    resume_name=filename,
                    file_size=file_size,
                )
            )

            # Send background confirmation email
            try:
                await self.email_service.send_recruitment_confirm_email(
                    email=payload.email,
                    name=payload.first_name,
                    job_title=job.title,
                )
            except Exception as mail_exc:
                logger.error("apply_to_job: confirmation email failed | exc=%s", str(mail_exc))

            full_app = await self.repo.get_application_by_id(application.id)
            return ApplicationResponse.model_validate(full_app)

        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("apply_to_job: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_job_by_ukey(self, ukey: str) -> JobResponse:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import select, and_
        
        stmt = select(JobPublishChannel).where(
            and_(JobPublishChannel.unique_key == ukey, JobPublishChannel.is_active == True)
        )
        res = await self.session.execute(stmt)
        chan = res.scalar_one_or_none()
        if not chan:
            raise AppException(message="Job publish channel not found or inactive.", status_code=status.HTTP_404_NOT_FOUND)
            
        job = await self.repo.get_job_by_id(chan.job_id)
        if not job or job.status == "CLOSED":
            raise AppException(message="Job not found or closed.", status_code=status.HTTP_404_NOT_FOUND)
            
        return JobResponse.model_validate(job)

    async def apply_to_job_by_ukey(self, ukey: str, payload: ApplicationCreate, resume_file: UploadFile) -> ApplicationResponse:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import select, and_
        
        stmt = select(JobPublishChannel).where(
            and_(JobPublishChannel.unique_key == ukey, JobPublishChannel.is_active == True)
        )
        res = await self.session.execute(stmt)
        chan = res.scalar_one_or_none()
        if not chan:
            raise AppException(message="Job publish channel not found or inactive.", status_code=status.HTTP_404_NOT_FOUND)
            
        job = await self.repo.get_job_by_id(chan.job_id)
        if not job or job.status == "CLOSED":
            raise AppException(message="Job not found or closed.", status_code=status.HTTP_404_NOT_FOUND)

        # Resume file validation
        filename = resume_file.filename or "resume.pdf"
        _, ext = os.path.splitext(filename.lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message="Invalid file extension. Only PDF, DOC, and DOCX are allowed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Check file size
        file_data = await resume_file.read()
        file_size = len(file_data)
        await resume_file.seek(0)

        if file_size > MAX_FILE_SIZE_BYTES:
            raise AppException(
                message="File size exceeds maximum limit of 5 MB.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Save resume securely
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        save_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(save_path, "wb") as f:
            f.write(file_data)

        # Create or get Candidate record
        source_val = "DIRECT"
        if chan.channel_name == "career_site":
            source_val = "Career Site"
        elif chan.channel_name == "public_link":
            source_val = "Public Sourcing Link"
        elif chan.channel_name == "internal_portal":
            source_val = "Internal Referral"
        else:
            source_val = chan.channel_name

        candidate = await self.repo.get_candidate_by_email(payload.email)
        if not candidate:
            candidate = await self.repo.create_candidate(
                first_name=payload.first_name,
                last_name=payload.last_name,
                email=payload.email.lower().strip(),
                phone=payload.phone,
                location=f"{payload.city}, {payload.state}, {payload.country}",
                years_experience=payload.experience_years,
                current_company=payload.current_company,
                current_role=payload.current_designation,
                expected_salary=payload.expected_ctc,
                resume_path=save_path,
                resume_name=filename,
                source=source_val,
                is_talent_pool=False,
            )
        else:
            candidate.resume_path = save_path
            candidate.resume_name = filename
            await self.session.flush()

        # Create application record
        app_data = payload.model_dump()
        app_data.pop("is_fresher", None)
        app_data["job_id"] = job.id
        app_data["company_id"] = job.company_id
        app_data["status"] = "APPLIED"
        app_data["candidate_id"] = candidate.id

        application = await self.repo.create_application(**app_data)

        # Save document path
        doc_kwargs = {
            "application_id": application.id,
            "document_type": "RESUME",
            "file_path": save_path,
            "file_name": filename,
            "file_size": file_size,
        }
        await self.repo.add_application_document(**doc_kwargs)

        await self.session.commit()

        import asyncio
        asyncio.create_task(
            self.screen_candidate_resume_task(
                application_id=application.id,
                candidate_id=candidate.id,
                job_id=job.id,
                resume_path=save_path,
                resume_name=filename,
                file_size=file_size,
            )
        )

        # Send confirmation email in background
        try:
            await self.email_service.send_recruitment_confirm_email(
                email=payload.email,
                name=payload.first_name,
                job_title=job.title,
            )
        except Exception as mail_exc:
            logger.error("apply_to_job_by_ukey: email failed | exc=%s", str(mail_exc))

        full_app = await self.repo.get_application_by_id(application.id)
        return ApplicationResponse.model_validate(full_app)

    # ------------------------------------------------------------------
    # Application Management (HR Evaluator)
    # ------------------------------------------------------------------

    async def list_applications(
        self,
        job_id: uuid.UUID | None,
        status: str | None,
        search: str | None,
        page: int,
        limit: int,
        company_id: uuid.UUID | None = None,
    ) -> ApplicationListResponse:
        try:
            offset = (page - 1) * limit
            apps = await self.repo.list_applications(
                job_id=job_id,
                status=status,
                search=search,
                company_id=company_id,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_applications(
                job_id=job_id,
                status=status,
                search=search,
                company_id=company_id,
            )

            # Map items to detailed dict to cover all frontend expectations
            items = []
            for a in apps:
                job_obj = None
                if a.job:
                    job_obj = {
                        "id": a.job.id,
                        "title": a.job.title,
                        "slug": a.job.slug,
                        "department": a.job.department,
                        "location": a.job.location,
                        "employment_type": a.job.employment_type,
                        "vacancies": a.job.vacancies,
                        "status": a.job.status,
                        "created_at": a.job.created_at,
                    }

                docs_list = []
                for d in (a.documents or []):
                    docs_list.append({
                        "id": d.id,
                        "document_type": d.document_type,
                        "file_name": d.file_name,
                        "file_size": d.file_size,
                        "uploaded_at": d.uploaded_at,
                    })

                items.append({
                    "id": a.id,
                    "job_id": a.job_id,
                    "candidate_id": a.candidate_id,
                    "company_id": a.company_id or (a.job.company_id if a.job else None),
                    "first_name": a.first_name,
                    "last_name": a.last_name,
                    "email": a.email,
                    "phone": a.phone,
                    "country": a.country,
                    "state": a.state,
                    "city": a.city,
                    "current_company": a.current_company,
                    "current_designation": a.current_designation,
                    "current_ctc": str(a.current_ctc) if a.current_ctc is not None else None,
                    "expected_ctc": str(a.expected_ctc) if a.expected_ctc is not None else None,
                    "notice_period": a.notice_period,
                    "highest_qualification": a.highest_qualification,
                    "experience_years": str(a.experience_years) if a.experience_years is not None else "0.0",
                    "linkedin_url": a.linkedin_url,
                    "portfolio_url": a.portfolio_url,
                    "cover_letter": a.cover_letter,
                    "status": a.status,
                    "created_at": a.created_at,
                    "applied_at": a.created_at,
                    "job_title": a.job.title if a.job else "",
                    "job": job_obj,
                    "documents": docs_list,
                })

            pages = math.ceil(total / limit) if limit > 0 else 0
            return ApplicationListResponse(items=items, total=total, page=page, limit=limit, pages=pages)
        except SQLAlchemyError as exc:
            logger.exception("list_applications: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_application(self, app_uuid: uuid.UUID) -> ApplicationResponse:
        try:
            app = await self.repo.get_application_by_id(app_uuid)
            if not app:
                raise AppException(message="Application not found.", status_code=status.HTTP_404_NOT_FOUND)
            return ApplicationResponse.model_validate(app)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_application: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_application_status(self, app_uuid: uuid.UUID, new_status: str) -> ApplicationResponse:
        try:
            app = await self.repo.get_application_by_id(app_uuid)
            if not app:
                raise AppException(message="Application not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.update_application_status(app_uuid, new_status)
            await self.session.commit()
            
            # Send rejection email if rejected
            if new_status.upper() == "REJECTED":
                try:
                    await self.email_service.send_recruitment_reject_email(
                        email=app.email,
                        name=app.first_name,
                        job_title=app.job.title,
                    )
                except Exception as mail_exc:
                    logger.error("update_application_status: rejection email failed | exc=%s", str(mail_exc))

            full_app = await self.repo.get_application_by_id(app_uuid)
            return ApplicationResponse.model_validate(full_app)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_application_status: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Interview Scheduling & Evaluation
    # ------------------------------------------------------------------

    async def initiate_interview(self, user_id: uuid.UUID, app_uuid: uuid.UUID, round_names: list[str]) -> InterviewResponse:
        logger.info("initiate_interview | user_id=%s | app_id=%s", user_id, app_uuid)
        try:
            app = await self.repo.get_application_by_id(app_uuid)
            if not app:
                raise AppException(message="Application not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Create Interview parent
            interview = await self.repo.create_interview(application_id=app_uuid, status="SCHEDULED", current_round_index=0)

            # Create Rounds in order
            for i, name in enumerate(round_names):
                await self.repo.create_interview_round(
                    interview_id=interview.id,
                    round_name=name,
                    round_order=i,
                    status="PENDING",
                )

            await self.repo.update_application_status(app_uuid, "INTERVIEW_SCHEDULED")
            await self.session.commit()

            # Send Interview Scheduling Invitation Email
            try:
                schedule_url = f"{settings.FRONTEND_BASE_URL}/schedule-interview?interview_id={interview.id}"
                await self.email_service.send_recruitment_interview_email(
                    email=app.email,
                    name=app.first_name,
                    job_title=app.job.title,
                    schedule_url=schedule_url,
                )
            except Exception as mail_exc:
                logger.error("initiate_interview: scheduling email failed | exc=%s", str(mail_exc))

            # Re-fetch interview
            full_interview = await self.repo.get_interview_by_id(interview.id)
            return InterviewResponse.model_validate(full_interview)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("initiate_interview: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def book_interview_schedule(
        self, interview_uuid: uuid.UUID, payload: InterviewScheduleCreate
    ) -> InterviewScheduleResponse:
        logger.info("book_interview_schedule | int_id=%s", interview_uuid)
        try:
            interview = await self.repo.get_interview_by_id(interview_uuid)
            if not interview:
                raise AppException(message="Interview not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Rule: only slots within the next 7 days allowed
            today = date.today()
            max_date = today + timedelta(days=7)
            if not (today <= payload.interview_date <= max_date):
                raise AppException(
                    message="You can only schedule interviews within the next 7 days.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Double booking check
            if await self.repo.check_double_booking(payload.interview_date, payload.interview_time):
                raise ConflictException(message="This time slot is already booked. Please choose another slot.")

            # Get current round
            current_idx = interview.current_round_index
            rounds_sorted = sorted(interview.rounds, key=lambda r: r.round_order)
            if current_idx >= len(rounds_sorted):
                raise AppException(message="All rounds for this interview have been completed.", status_code=status.HTTP_400_BAD_REQUEST)
            current_round = rounds_sorted[current_idx]

            # Save schedule
            sched_data = payload.model_dump()
            sched_data["interview_id"] = interview_uuid
            sched_data["round_id"] = current_round.id

            sched = await self.repo.create_interview_schedule(**sched_data)
            await self.session.commit()

            # Fetch schedule
            result = await self.session.execute(
                select(InterviewSchedule).where(InterviewSchedule.id == sched.id)
            )
            obj = result.scalar_one()
            
            # Map time to string for output schema
            time_str = obj.interview_time.strftime("%H:%M:%S") if isinstance(obj.interview_time, time) else str(obj.interview_time)
            
            return InterviewScheduleResponse(
                id=obj.id,
                interview_id=obj.interview_id,
                round_id=obj.round_id,
                interview_date=obj.interview_date,
                interview_time=time_str,
                mode=obj.mode,
                meeting_url=obj.meeting_url,
                office_address=obj.office_address,
                created_at=obj.created_at,
            )

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("book_interview_schedule: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_interviews(self, status: str | None, page: int, limit: int) -> list[InterviewResponse]:
        try:
            offset = (page - 1) * limit
            ints = await self.repo.list_interviews(status=status, limit=limit, offset=offset)
            return [InterviewResponse.model_validate(i) for i in ints]
        except SQLAlchemyError as exc:
            logger.exception("list_interviews: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_interview(self, interview_uuid: uuid.UUID) -> InterviewResponse:
        try:
            interview = await self.repo.get_interview_by_id(interview_uuid)
            if not interview:
                raise AppException(message="Interview not found.", status_code=status.HTTP_404_NOT_FOUND)
            return InterviewResponse.model_validate(interview)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_interview: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def complete_interview_round(
        self, round_uuid: uuid.UUID, decision: str, payload: CompleteRoundRequest
    ) -> InterviewResponse:
        logger.info("complete_interview_round | round_id=%s | decision=%s", round_uuid, decision)
        try:
            round_obj = await self.repo.get_interview_round_by_id(round_uuid)
            if not round_obj:
                raise AppException(message="Interview round not found.", status_code=status.HTTP_440_NOT_FOUND if hasattr(status, "HTTP_440_NOT_FOUND") else status.HTTP_404_NOT_FOUND)

            interview = await self.repo.get_interview_by_id(round_obj.interview_id)
            if not interview:
                raise AppException(message="Interview not found.", status_code=status.HTTP_404_NOT_FOUND)

            decision = decision.upper()
            if decision not in ROUND_STATUS_VALUES:
                raise AppException(message="Invalid round status decision.", status_code=status.HTTP_400_BAD_REQUEST)

            await self.repo.update_interview_round(
                round_uuid,
                feedback=payload.feedback.strip(),
                score=payload.score.strip(),
                interviewer_name=payload.interviewer_name.strip(),
                status=decision,
                conducted_at=datetime.now(timezone.utc),
            )

            rounds_sorted = sorted(interview.rounds, key=lambda r: r.round_order)
            
            if decision == "PASSED":
                next_index = interview.current_round_index + 1
                if next_index >= len(rounds_sorted):
                    # All rounds completed successfully
                    await self.repo.update_interview_status(interview.id, "COMPLETED", next_index)
                    await self.repo.update_application_status(interview.application_id, "INTERVIEW_COMPLETED")
                else:
                    await self.repo.update_interview_status(interview.id, "SCHEDULED", next_index)
            elif decision == "REJECTED":
                await self.repo.update_interview_status(interview.id, "REJECTED")
                await self.repo.update_application_status(interview.application_id, "REJECTED")
            elif decision == "HOLD":
                await self.repo.update_interview_status(interview.id, "HOLD")
                await self.repo.update_application_status(interview.application_id, "HOLD")

            await self.session.commit()
            full_int = await self.repo.get_interview_by_id(interview.id)
            return InterviewResponse.model_validate(full_int)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("complete_interview_round: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Offer Management & Employee Conversion
    # ------------------------------------------------------------------

    async def create_offer(self, user_id: uuid.UUID, app_uuid: uuid.UUID, payload: OfferCreate) -> OfferResponse:
        logger.info("create_offer | user_id=%s | app_id=%s", user_id, app_uuid)
        try:
            app = await self.repo.get_application_by_id(app_uuid)
            if not app:
                raise AppException(message="Application not found.", status_code=status.HTTP_404_NOT_FOUND)

            offer_kwargs = {
                "application_id": app_uuid,
                "ctc": payload.ctc,
                "joining_date": payload.joining_date,
                "offer_expiry_date": payload.offer_expiry_date,
                "status": "SENT",
                "created_by": user_id,
            }

            offer = await self.repo.create_offer(**offer_kwargs)

            # Seed an empty offer document record to satisfy storage
            doc_kwargs = {
                "offer_id": offer.id,
                "file_path": f"uploads/offers/offer_{offer.id}.pdf",
                "file_name": f"Offer_Letter_{app.first_name}.pdf",
            }
            await self.repo.create_offer_document(**doc_kwargs)

            await self.repo.update_application_status(app_uuid, "OFFER_SENT")
            await self.session.commit()

            # Send Job Offer Email
            try:
                offer_url = f"{settings.FRONTEND_BASE_URL}/offers/{offer.id}"
                await self.email_service.send_recruitment_offer_email(
                    email=app.email,
                    name=app.first_name,
                    job_title=app.job.title,
                    ctc=str(payload.ctc),
                    joining_date=str(payload.joining_date),
                    expiry_date=str(payload.offer_expiry_date),
                    offer_url=offer_url,
                )
            except Exception as mail_exc:
                logger.error("create_offer: offer email failed | exc=%s", str(mail_exc))

            # Re-fetch offer
            full_offer = await self.repo.get_offer_by_id(offer.id)
            return OfferResponse.model_validate(full_offer)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_offer: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_offer_status(self, offer_uuid: uuid.UUID, new_status: str) -> OfferResponse:
        try:
            offer = await self.repo.get_offer_by_id(offer_uuid)
            if not offer:
                raise AppException(message="Offer not found.", status_code=status.HTTP_404_NOT_FOUND)

            new_status = new_status.upper()
            if new_status not in OFFER_STATUS_VALUES:
                raise AppException(message="Invalid offer status.", status_code=status.HTTP_400_BAD_REQUEST)

            await self.repo.update_offer_status(offer_uuid, new_status)
            
            app_status = f"OFFER_{new_status}"
            await self.repo.update_application_status(offer.application_id, app_status)

            await self.session.commit()
            full_offer = await self.repo.get_offer_by_id(offer_uuid)
            return OfferResponse.model_validate(full_offer)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_offer_status: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def convert_candidate_to_employee(self, user_id: uuid.UUID, app_uuid: uuid.UUID) -> None:
        logger.info("convert_candidate_to_employee | user_id=%s | app_id=%s", user_id, app_uuid)
        try:
            app = await self.repo.get_application_by_id(app_uuid)
            if not app:
                raise AppException(message="Application not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Check status must be OFFER_ACCEPTED
            if app.status != "OFFER_ACCEPTED":
                raise AppException(message="Candidate must accept the offer before conversion.", status_code=status.HTTP_400_BAD_REQUEST)

            # Sequential Employee ID Format: EMP-YYYYMM-NNNN
            year_month = datetime.now(timezone.utc).strftime("%Y%m")
            prefix = f"EMP-{year_month}-"
            from app.models.employee import Employee
            from sqlalchemy import select
            res_id = await self.session.execute(
                select(Employee.employee_id)
                .where(Employee.employee_id.like(prefix + "%"))
                .order_by(Employee.employee_id.desc())
                .limit(1)
            )
            last_id = res_id.scalar_one_or_none()
            if last_id:
                try:
                    seq = int(last_id.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            employee_id = f"{prefix}{seq:04d}"

            # Auto generate company email
            from app.services.employee_service import generate_company_email
            company_email = await generate_company_email(
                app.first_name, app.last_name, settings.COMPANY_EMAIL_DOMAIN, self.session
            )

            # Create User record
            temp_password = generate_temp_password()
            password_hash = hash_password(temp_password)
            full_name = app.first_name.strip() + " " + app.last_name.strip()
            
            from app.models.user import UserRole
            user = await self.auth_repo.create_user(
                name=full_name,
                email=company_email,
                phone=app.phone,
                password_hash=password_hash,
                role=UserRole.EMPLOYEE,
                is_active=False,
                is_verified=False,
                must_change_password=True,
            )

            # Get joining date from offer
            offer = await self.repo.get_offer_by_application_id(app_uuid)
            joining_date = offer.joining_date if offer else date.today()

            # Create Employee profile record
            emp_kwargs = {
                "user_id": user.id,
                "employee_id": employee_id,
                "first_name": app.first_name.strip(),
                "last_name": app.last_name.strip(),
                "personal_email": app.email.lower(),
                "company_email": company_email,
                "phone": app.phone,
                "department": app.job.department,
                "designation": app.job.designation,
                "joining_date": joining_date,
                "employment_type": app.job.employment_type,
                "employment_status": "PROBATION",
                "status": "CREATED",
                "created_by": user_id,
            }
            new_emp = await self.employee_repo.create_employee(**emp_kwargs)

            # Seed onboarding steps
            from app.models.employee_onboarding import EmployeeOnboarding
            onboarding_steps = [
                "Submit Address Verification Docs",
                "Submit Education Certificates",
                "Submit Prior Work Experience Docs",
                "Sign Code of Conduct",
                "Setup Bank Account Details",
            ]
            for i, step_name in enumerate(onboarding_steps):
                step = EmployeeOnboarding(
                    employee_id=new_emp.id,
                    step_name=step_name,
                    step_order=i,
                    status="PENDING",
                )
                self.session.add(step)

            # Shift application status
            await self.repo.update_application_status(app_uuid, "EMPLOYEE_CREATED")

            await self.session.commit()

            # Send welcoming & activation credentials
            activation_token = uuid.uuid4().hex
            activation_url = settings.FRONTEND_BASE_URL + "/activate?token=" + activation_token + "&employee_id=" + str(new_emp.id)
            try:
                await self.email_service.send_employee_activation_email(
                    email=company_email,
                    name=app.first_name,
                    employee_id=employee_id,
                    activation_url=activation_url,
                    temp_password=temp_password,
                    expiry_hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS,
                )
            except Exception as mail_exc:
                logger.error("convert_candidate_to_employee: email delivery failed | exc=%s", str(mail_exc))

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("convert_candidate_to_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Candidate / Talent Pool
    # ------------------------------------------------------------------

    async def create_candidate(self, payload: CandidateCreate) -> CandidateResponse:
        try:
            cand_data = payload.model_dump()
            cand = await self.repo.create_candidate(**cand_data)
            await self.session.commit()
            return CandidateResponse.model_validate(cand)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_candidate: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def _recalculate_candidate_ats_score(self, candidate: Any) -> dict[str, Any]:
        """Recalculate dynamic ATS score on the fly and optionally save to DB if resume document exists."""
        from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
        from app.models.recruitment import JobSkill, Application
        from app.services.ats_scoring_service import ATSScoringService
        from sqlalchemy import select

        # Get latest resume doc
        resume_stmt = select(AIResumeDocument).where(AIResumeDocument.candidate_id == candidate.id).order_by(AIResumeDocument.created_at.desc())
        resume_res = await self.session.execute(resume_stmt)
        resume = resume_res.scalars().first()

        parsed_data = resume.parsed_data if (resume and resume.parsed_data) else {}
        
        # Prepare candidate data
        candidate_data = {
            "candidate_name": f"{candidate.first_name} {candidate.last_name}".strip(),
            "email": candidate.email,
            "phone": candidate.phone,
            "skills": candidate.skills or parsed_data.get("skills") or [],
            "total_experience_years": float(candidate.years_experience) if candidate.years_experience is not None else (parsed_data.get("total_experience_years") or 0.0),
            "current_designation": candidate.current_role or parsed_data.get("current_designation") or "",
            "education": parsed_data.get("education") or [],
            "projects": parsed_data.get("projects") or [],
            "certifications": parsed_data.get("certifications") or [],
            "summary": candidate.summary or parsed_data.get("summary") or "",
            "raw_text": resume.raw_text if resume else "",
        }

        # Find latest application and job via explicit database query to prevent lazy loading issues
        from sqlalchemy.orm import selectinload
        app_stmt = select(Application).options(selectinload(Application.job)).where(Application.candidate_id == candidate.id).order_by(Application.created_at.desc())
        app_res = await self.session.execute(app_stmt)
        latest_app = app_res.scalars().first()

        job_data = {
            "title": "Target Role",
            "job_description": "",
            "min_experience": 0.0,
            "skills": [],
        }

        job = None
        job_exists = False
        if latest_app:
            job = latest_app.job
            if job:
                job_exists = True
                job_skills_stmt = select(JobSkill).where(JobSkill.job_id == job.id)
                job_skills_res = await self.session.execute(job_skills_stmt)
                job_skills = [s.skill_name for s in job_skills_res.scalars().all()]
                job_data = {
                    "title": job.title,
                    "job_description": job.job_description or "",
                    "min_experience": float(job.min_experience or 0.0),
                    "skills": job_skills,
                }

        # Calculate score using the engine
        ats_service = ATSScoringService()
        ats_res = ats_service.calculate_ats_score(candidate_data, job_data)

        # Determine a valid job_id for the FK constraint
        target_job_id = None
        if job_exists and job:
            target_job_id = job.id
        else:
            from app.models.recruitment import Job
            any_job_stmt = select(Job.id).limit(1)
            any_job_res = await self.session.execute(any_job_stmt)
            target_job_id = any_job_res.scalar()

        # If resume and a valid job exist, persist to CandidateMatchScore
        if resume and target_job_id:
            score_stmt = select(CandidateMatchScore).where(
                CandidateMatchScore.resume_document_id == resume.id
            )
            score_res = await self.session.execute(score_stmt)
            score_record = score_res.scalar_one_or_none()

            if not score_record:
                score_record = CandidateMatchScore(
                    resume_document_id=resume.id,
                    job_id=target_job_id,
                    candidate_id=candidate.id,
                )
                self.session.add(score_record)
            else:
                # Make sure job_id is updated to target_job_id to satisfy FK
                score_record.job_id = target_job_id

            score_record.overall_match_score = ats_res["overall_ats_score"] / 100.0 if ats_res["overall_ats_score"] > 1.0 else ats_res["overall_ats_score"]
            score_record.skill_match_score = ats_res["skill_match_score"] / 100.0
            score_record.experience_match_score = ats_res["experience_match_score"] / 100.0
            score_record.education_match_score = ats_res["education_match_score"] / 100.0
            score_record.domain_match_score = ats_res.get("keyword_match_score", 0.0) / 100.0
            score_record.industry_match_score = ats_res.get("projects_score", 0.0) / 100.0
            score_record.location_match_score = ats_res.get("certifications_score", 0.0) / 100.0
            score_record.salary_match_score = ats_res.get("resume_quality_score", 0.0) / 100.0
            score_record.availability_score = ats_res.get("job_match", 0.0) / 100.0
            score_record.matching_skills = ats_res["matched_skills"]
            score_record.missing_skills = ats_res["missing_skills"]
            score_record.extra_skills = ats_res["extra_skills"]
            score_record.analysis_data = {
                "ats_breakdown": ats_res,
                "score_breakdown": ats_res.get("score_breakdown", {}),
                "recommendations": ats_res.get("recommendations", []),
            }
            score_record.recommendation = "SHORTLIST" if ats_res["overall_ats_score"] >= 75 else "REVIEW"
            await self.session.commit()

        return ats_res

    async def get_candidate(self, candidate_uuid: uuid.UUID) -> CandidateResponse:
        cand = await self.repo.get_candidate_by_id(candidate_uuid)
        if not cand:
            raise AppException(message="Candidate profile not found.", status_code=status.HTTP_404_NOT_FOUND)
        
        # Enrich candidate fields from application if null
        if cand.applications:
            sorted_apps = sorted(cand.applications, key=lambda a: a.created_at or datetime.min, reverse=True)
            latest_app = sorted_apps[0]
            if not cand.current_company and latest_app.current_company:
                cand.current_company = latest_app.current_company
            if not cand.current_role and latest_app.current_designation:
                cand.current_role = latest_app.current_designation
            if not cand.expected_salary and latest_app.expected_ctc:
                cand.expected_salary = latest_app.expected_ctc
            if not cand.summary:
                job_name = latest_app.job.title if latest_app.job else "Target Role"
                cand.summary = f"Candidate applied for {job_name} with {cand.years_experience} years of experience."
            if not cand.skills:
                cand.skills = [s for s in [latest_app.current_designation, latest_app.highest_qualification] if s]
            if not cand.tags:
                cand.tags = [t for t in ["Applicant", latest_app.status] if t]

        # Fetch dynamic AI matching scores if they exist
        from app.models.ai_recruitment import CandidateMatchScore
        from sqlalchemy import select
        score_res = await self.session.execute(
            select(CandidateMatchScore)
            .where(CandidateMatchScore.candidate_id == candidate_uuid)
            .order_by(CandidateMatchScore.overall_match_score.desc())
            .limit(1)
        )
        score_record = score_res.scalar_one_or_none()
        if score_record:
            score_val = score_record.overall_match_score
            cand.ats_score = int(score_val * 100) if score_val <= 1.0 else int(score_val)
            skill_val = score_record.skill_match_score
            cand.job_match = int(skill_val * 100) if skill_val <= 1.0 else int(skill_val)
        else:
            # Dynamic calculation on-the-fly
            ats_res = await self._recalculate_candidate_ats_score(cand)
            cand.ats_score = int(ats_res["overall_ats_score"])
            cand.job_match = int(ats_res["job_match"])

        return CandidateResponse.model_validate(cand)

    async def list_candidates(
        self,
        is_talent_pool: bool | None,
        search: str | None,
        tag: str | None,
        page: int,
        limit: int,
        company_id: uuid.UUID | None = None,
    ) -> dict:
        try:
            offset = (page - 1) * limit
            cands = await self.repo.list_candidates(
                is_talent_pool=is_talent_pool,
                search=search,
                tag=tag,
                limit=limit,
                offset=offset,
                company_id=company_id,
            )
            total = await self.repo.count_candidates(
                is_talent_pool=is_talent_pool,
                search=search,
                tag=tag,
                company_id=company_id,
            )

            # Bulk load match scores for the page of candidates
            from app.models.ai_recruitment import CandidateMatchScore
            from app.models.recruitment import Application
            from sqlalchemy import select, or_
            from sqlalchemy.orm import selectinload

            cand_ids = [c.id for c in cands]
            score_res = await self.session.execute(
                select(CandidateMatchScore).where(CandidateMatchScore.candidate_id.in_(cand_ids))
            )
            scores = score_res.scalars().all()
            
            # Map: candidate_id -> best matching score record
            score_map: dict = {}
            for s in scores:
                existing = score_map.get(s.candidate_id)
                if existing is None or s.overall_match_score > existing.overall_match_score:
                    score_map[s.candidate_id] = s
            
            for c in cands:
                best = score_map.get(c.id)
                if best is not None:
                    score_val = best.overall_match_score
                    c.ats_score = int(score_val * 100) if score_val <= 1.0 else int(score_val)
                    skill_val = best.skill_match_score
                    c.job_match = int(skill_val * 100) if skill_val <= 1.0 else int(skill_val)
                else:
                    # Dynamic calculation on-the-fly
                    ats_res = await self._recalculate_candidate_ats_score(c)
                    c.ats_score = int(ats_res["overall_ats_score"])
                    c.job_match = int(ats_res["job_match"])

            items = []
            for c in cands:
                cand_dict = CandidateResponse.model_validate(c).model_dump(mode="json")
                cand_dict["candidate_id"] = c.id
                cand_dict["name"] = f"{c.first_name} {c.last_name}".strip()
                cand_dict["application_id"] = None
                cand_dict["job_id"] = None
                cand_dict["job_title"] = None
                cand_dict["status"] = "APPLIED"

                latest_app = None
                if c.applications:
                    sorted_apps = sorted(c.applications, key=lambda a: a.created_at or datetime.min, reverse=True)
                    latest_app = sorted_apps[0]
                elif c.email:
                    app_res = await self.session.execute(
                        select(Application)
                        .options(selectinload(Application.job))
                        .where(Application.email.ilike(c.email.strip()))
                        .order_by(Application.created_at.desc())
                        .limit(1)
                    )
                    latest_app = app_res.scalar_one_or_none()

                if latest_app:
                    cand_dict["application_id"] = latest_app.id
                    cand_dict["job_id"] = latest_app.job_id
                    cand_dict["job_title"] = latest_app.job.title if latest_app.job else None
                    cand_dict["status"] = latest_app.status

                items.append(cand_dict)

            pages = math.ceil(total / limit) if limit > 0 else 0
            return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}
        except SQLAlchemyError as exc:
            logger.exception("list_candidates: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_candidate(self, candidate_uuid: uuid.UUID, payload: CandidateUpdate) -> CandidateResponse:
        try:
            cand_data = {k: v for k, v in payload.model_dump().items() if v is not None}
            await self.repo.update_candidate(candidate_uuid, **cand_data)
            await self.session.commit()
            cand = await self.repo.get_candidate_by_id(candidate_uuid)
            return CandidateResponse.model_validate(cand)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_candidate: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_candidate(self, candidate_uuid: uuid.UUID) -> None:
        try:
            await self.repo.delete_candidate(candidate_uuid)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_interview_feedback: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def screen_candidate_resume_task(
        self,
        application_id: uuid.UUID,
        candidate_id: uuid.UUID,
        job_id: uuid.UUID,
        resume_path: str,
        resume_name: str,
        file_size: int,
    ) -> None:
        """Asynchronously parses candidate resume and generates AI JD match score."""
        from app.db.database import AsyncSessionLocal
        from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
        from app.models.recruitment import Job, Candidate
        from app.agents.resume_parser import ResumeParserAgent
        from app.agents.candidate_matcher import CandidateMatcherAgent
        from app.llm.client import get_llm_client
        from app.ocr.engine_selector import get_ocr_selector
        from sqlalchemy import select
        import logging

        logger = logging.getLogger(__name__)
        logger.info("Starting background AI resume screening for candidate_id=%s", candidate_id)

        async with AsyncSessionLocal() as session:
            try:
                # 1. Create AIResumeDocument entry
                doc = AIResumeDocument(
                    application_id=application_id,
                    candidate_id=candidate_id,
                    file_path=resume_path,
                    file_name=resume_name,
                    file_size=file_size,
                    file_type=resume_name.split(".")[-1].lower() if "." in resume_name else "pdf",
                    parse_status="PROCESSING",
                )
                session.add(doc)
                await session.commit()
                await session.refresh(doc)

                # 2. Fetch candidate and parse file or construct synthetic profile text
                llm = get_llm_client()
                
                cand_res = await session.execute(select(Candidate).where(Candidate.id == candidate_id))
                cand = cand_res.scalar_one_or_none()
                if not cand:
                    logger.error("AI screening failed: Candidate not found")
                    return

                import os
                if resume_path and os.path.exists(resume_path):
                    ocr = get_ocr_selector()
                    agent = ResumeParserAgent(llm_client=llm, ocr_selector=ocr)
                    parsed_resume = await agent.parse_file(resume_path)
                    parsed_data_dict = parsed_resume.to_dict()
                    raw_text = (parsed_resume.raw_text or "")[:10000]
                    engine_used = parsed_resume.engine_used
                    c_name = parsed_resume.name
                    c_email = parsed_resume.email
                    c_exp = parsed_resume.years_experience
                    c_summary = parsed_resume.summary
                    c_skills = parsed_resume.all_skills_flat
                else:
                    parsed_data_dict = {
                        "name": f"{cand.first_name} {cand.last_name}",
                        "email": cand.email,
                        "phone": cand.phone,
                        "address": cand.location,
                        "years_experience": float(cand.years_experience or 0.0),
                        "skills": cand.skills or [],
                        "summary": cand.summary or "",
                        "current_company": cand.current_company or "",
                        "current_designation": cand.current_role or "",
                        "expected_salary": float(cand.expected_salary or 0.0),
                    }
                    raw_text = f"""
                    Candidate Profile Summary:
                    Name: {cand.first_name} {cand.last_name}
                    Email: {cand.email}
                    Phone: {cand.phone}
                    Location: {cand.location}
                    Experience: {cand.years_experience} years
                    Current Role: {cand.current_role or "N/A"}
                    Current Company: {cand.current_company or "N/A"}
                    Skills: {", ".join(cand.skills) if cand.skills else "N/A"}
                    Summary: {cand.summary or "N/A"}
                    """
                    engine_used = "ProfileExtractor"
                    c_name = f"{cand.first_name} {cand.last_name}"
                    c_email = cand.email
                    c_exp = float(cand.years_experience or 0.0)
                    c_summary = cand.summary
                    c_skills = cand.skills or []

                # 3. Update AIResumeDocument with parsed data
                doc.parsed_data = parsed_data_dict
                doc.raw_text = raw_text
                doc.parse_status = "COMPLETED"
                doc.ocr_engine_used = engine_used
                doc.candidate_name = c_name
                doc.candidate_email = c_email
                doc.years_experience = c_exp
                await session.commit()

                # 4. Fetch the Job Details
                job_res = await session.execute(select(Job).where(Job.id == job_id))
                job = job_res.scalar_one_or_none()
                if not job:
                    logger.error("AI screening failed: Job not found")
                    return

                # Construct Job Description text
                jd_text = job.job_description or ""
                if job.requirements:
                    jd_text += "\n\nRequirements:\n" + job.requirements
                if job.responsibilities:
                    jd_text += "\n\nResponsibilities:\n" + job.responsibilities

                # 5. Run Matcher Agent
                matcher = CandidateMatcherAgent(llm_client=llm)
                result = await matcher.match(
                    resume_text=doc.raw_text,
                    jd_text=jd_text,
                    candidate_metadata={
                        "expected_salary": parsed_data_dict.get("expected_salary"),
                        "notice_period": parsed_data_dict.get("notice_period"),
                        "location": parsed_data_dict.get("address"),
                    },
                )

                # 6. Save Match Score to DB
                score_record = CandidateMatchScore(
                    resume_document_id=doc.id,
                    job_id=job_id,
                    candidate_id=candidate_id,
                    overall_match_score=result.overall_match_score,
                    skill_match_score=result.skill_match_score,
                    experience_match_score=result.experience_match_score,
                    education_match_score=result.education_match_score,
                    domain_match_score=result.domain_match_score,
                    industry_match_score=result.industry_match_score,
                    location_match_score=result.location_match_score,
                    salary_match_score=result.salary_match_score,
                    availability_score=result.availability_score,
                    ai_confidence_score=result.ai_confidence_score,
                    matching_skills=result.matching_skills,
                    missing_skills=result.missing_skills,
                    extra_skills=result.extra_skills,
                    recommendation="HIRE" if result.overall_match_score >= 0.75 else "REJECT" if result.overall_match_score < 0.4 else "REVIEW",
                )
                session.add(score_record)

                # 7. Update Candidate profile text with summary & skills from parsing if empty
                if cand:
                    if not cand.summary:
                        cand.summary = c_summary
                    if not cand.skills and c_skills:
                        cand.skills = c_skills[:30]

                await session.commit()
                logger.info("AI screening completed successfully for candidate_id=%s score=%s", candidate_id, result.overall_match_score)

            except Exception as e:
                logger.exception("Error during background AI resume screening: %s", str(e))

    async def match_candidate_against_jobs_task(
        self,
        candidate_id: uuid.UUID,
        doc_id: uuid.UUID,
        raw_text: str,
        candidate_metadata: dict,
    ) -> None:
        """Background worker that matches a candidate against all published jobs."""
        from app.db.database import AsyncSessionLocal
        from app.models.recruitment import Job
        from app.models.ai_recruitment import CandidateMatchScore
        from app.agents.candidate_matcher import CandidateMatcherAgent
        from app.llm.client import get_llm_client
        from sqlalchemy import select
        import logging

        logger = logging.getLogger(__name__)
        logger.info("Starting background AI job matching for candidate_id=%s", candidate_id)

        async with AsyncSessionLocal() as session:
            try:
                # 1. Fetch all published/active jobs
                jobs_res = await session.execute(select(Job).where(Job.status == "PUBLISHED"))
                jobs = jobs_res.scalars().all()
                if not jobs:
                    logger.info("No published jobs found to match candidate_id=%s", candidate_id)
                    return

                llm = get_llm_client()
                matcher = CandidateMatcherAgent(llm_client=llm)

                for job in jobs:
                    # Check if match score already exists for this candidate/job combination
                    existing_res = await session.execute(
                        select(CandidateMatchScore)
                        .where(CandidateMatchScore.candidate_id == candidate_id)
                        .where(CandidateMatchScore.job_id == job.id)
                    )
                    if existing_res.scalar_one_or_none():
                        logger.info("Match score already exists for candidate_id=%s, job_id=%s. Skipping.", candidate_id, job.id)
                        continue

                    jd_text = job.job_description or ""
                    if job.requirements:
                        jd_text += "\n\nRequirements:\n" + job.requirements
                    if job.responsibilities:
                        jd_text += "\n\nResponsibilities:\n" + job.responsibilities

                    # Match
                    result = await matcher.match(
                        resume_text=raw_text,
                        jd_text=jd_text,
                        candidate_metadata=candidate_metadata,
                    )

                    # Save Match Score
                    score_record = CandidateMatchScore(
                        resume_document_id=doc_id,
                        job_id=job.id,
                        candidate_id=candidate_id,
                        overall_match_score=result.overall_match_score,
                        skill_match_score=result.skill_match_score,
                        experience_match_score=result.experience_match_score,
                        education_match_score=result.education_match_score,
                        domain_match_score=result.domain_match_score,
                        industry_match_score=result.industry_match_score,
                        location_match_score=result.location_match_score,
                        salary_match_score=result.salary_match_score,
                        availability_score=result.availability_score,
                        ai_confidence_score=result.ai_confidence_score,
                        matching_skills=result.matching_skills,
                        missing_skills=result.missing_skills,
                        extra_skills=result.extra_skills,
                        recommendation="HIRE" if result.overall_match_score >= 0.75 else "REJECT" if result.overall_match_score < 0.4 else "REVIEW",
                    )
                    session.add(score_record)

                await session.commit()
                logger.info("Auto job matching completed for candidate_id=%s", candidate_id)
            except Exception as e:
                logger.exception("Error during auto job matching task: %s", str(e))

    # ------------------------------------------------------------------
    # Job Requisitions
    # ------------------------------------------------------------------

    async def create_requisition(self, user_id: uuid.UUID, payload: JobRequisitionCreate) -> JobRequisitionResponse:
        try:
            req_data = payload.model_dump()
            req_data["requested_by"] = user_id
            req_data["status"] = "PENDING"
            req = await self.repo.create_requisition(**req_data)
            await self.session.commit()
            full_req = await self.repo.get_requisition_by_id(req.id)
            return JobRequisitionResponse.model_validate(full_req)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_requisition: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_requisition(self, req_uuid: uuid.UUID) -> JobRequisitionResponse:
        req = await self.repo.get_requisition_by_id(req_uuid)
        if not req:
            raise AppException(message="Requisition not found.", status_code=status.HTTP_404_NOT_FOUND)
        return JobRequisitionResponse.model_validate(req)

    async def list_requisitions(self, status: str | None, page: int, limit: int) -> dict:
        try:
            offset = (page - 1) * limit
            reqs = await self.repo.list_requisitions(status=status, limit=limit, offset=offset)
            total = await self.repo.count_requisitions(status=status)
            items = [JobRequisitionResponse.model_validate(r) for r in reqs]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}
        except SQLAlchemyError as exc:
            logger.exception("list_requisitions: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def approve_requisition(self, user_id: uuid.UUID, req_uuid: uuid.UUID, approve: bool) -> JobRequisitionResponse:
        try:
            new_status = "APPROVED" if approve else "REJECTED"
            await self.repo.update_requisition_status(req_uuid, new_status, approved_by=user_id)
            
            # If approved, automatically promote/convert it to a published or draft Job posting!
            req = await self.repo.get_requisition_by_id(req_uuid)
            if approve:
                # Create Job from Requisition
                slug = await generate_job_slug(req.title, self.repo)
                await self.repo.create_job(
                    title=req.title,
                    slug=slug,
                    department=req.department,
                    designation=req.title,
                    vacancies=req.vacancies,
                    min_experience=req.min_experience,
                    max_experience=req.max_experience,
                    min_salary=req.min_salary,
                    max_salary=req.max_salary,
                    job_description=req.description,
                    status="DRAFT",
                    created_by=user_id,
                )
            await self.session.commit()
            return JobRequisitionResponse.model_validate(req)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("approve_requisition: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------

    async def create_vendor(self, payload: RecruitmentVendorCreate) -> RecruitmentVendorResponse:
        try:
            vendor = await self.repo.create_vendor(**payload.model_dump())
            await self.session.commit()
            return RecruitmentVendorResponse.model_validate(vendor)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def get_vendor(self, vendor_uuid: uuid.UUID) -> RecruitmentVendorResponse:
        vendor = await self.repo.get_vendor_by_id(vendor_uuid)
        if not vendor:
            raise AppException(message="Vendor not found.", status_code=status.HTTP_404_NOT_FOUND)
        return RecruitmentVendorResponse.model_validate(vendor)

    async def list_vendors(self, page: int, limit: int) -> dict:
        try:
            offset = (page - 1) * limit
            vendors = await self.repo.list_vendors(limit=limit, offset=offset)
            total = await self.repo.count_vendors()
            items = [RecruitmentVendorResponse.model_validate(v) for v in vendors]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}
        except SQLAlchemyError as exc:
            raise DatabaseException() from exc

    async def update_vendor(self, vendor_uuid: uuid.UUID, payload: RecruitmentVendorUpdate) -> RecruitmentVendorResponse:
        try:
            await self.repo.update_vendor(vendor_uuid, **{k: v for k, v in payload.model_dump().items() if v is not None})
            await self.session.commit()
            vendor = await self.repo.get_vendor_by_id(vendor_uuid)
            return RecruitmentVendorResponse.model_validate(vendor)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def delete_vendor(self, vendor_uuid: uuid.UUID) -> None:
        try:
            await self.repo.delete_vendor(vendor_uuid)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # CRM Notes
    # ------------------------------------------------------------------

    async def create_crm_note(self, user_id: uuid.UUID, payload: CandidateCrmNoteCreate) -> CandidateCrmNoteResponse:
        try:
            note_data = payload.model_dump()
            note_data["author_id"] = user_id
            note = await self.repo.create_crm_note(**note_data)
            await self.session.commit()
            
            # Fetch complete note details
            from app.models.recruitment import CandidateCrmNote
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            result = await self.session.execute(
                select(CandidateCrmNote).where(CandidateCrmNote.id == note.id).options(selectinload(CandidateCrmNote.author))
            )
            return CandidateCrmNoteResponse.model_validate(result.scalar_one())
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def list_crm_notes(self, candidate_uuid: uuid.UUID) -> list[CandidateCrmNoteResponse]:
        notes = await self.repo.list_crm_notes_for_candidate(candidate_uuid)
        return [CandidateCrmNoteResponse.model_validate(n) for n in notes]

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------

    async def create_referral(self, payload: CandidateReferralCreate) -> CandidateReferralResponse:
        try:
            ref = await self.repo.create_referral(**payload.model_dump())
            await self.session.commit()
            full_ref = await self.repo.get_referral_by_id(ref.id)
            return CandidateReferralResponse.model_validate(full_ref)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def list_referrals(self, page: int, limit: int) -> dict:
        try:
            offset = (page - 1) * limit
            refs = await self.repo.list_referrals(limit=limit, offset=offset)
            total = await self.repo.count_referrals()
            items = [CandidateReferralResponse.model_validate(r) for r in refs]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}
        except SQLAlchemyError as exc:
            raise DatabaseException() from exc

    async def update_referral_status(self, referral_uuid: uuid.UUID, status: str, reward_status: str | None = None) -> CandidateReferralResponse:
        try:
            await self.repo.update_referral_status(referral_uuid, status, reward_status)
            await self.session.commit()
            ref = await self.repo.get_referral_by_id(referral_uuid)
            return CandidateReferralResponse.model_validate(ref)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Scorecards
    # ------------------------------------------------------------------

    async def create_scorecard_template(self, payload: ScorecardTemplateCreate) -> ScorecardTemplateResponse:
        try:
            tpl = await self.repo.create_scorecard_template(**payload.model_dump())
            await self.session.commit()
            return ScorecardTemplateResponse.model_validate(tpl)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def list_scorecard_templates(self, department: str | None = None) -> list[ScorecardTemplateResponse]:
        templates = await self.repo.list_scorecard_templates(department)
        return [ScorecardTemplateResponse.model_validate(t) for t in templates]

    async def submit_scorecard(self, user_id: uuid.UUID, payload: ScorecardSubmissionCreate) -> ScorecardSubmissionResponse:
        try:
            data = payload.model_dump()
            data["submitted_by"] = user_id
            submission = await self.repo.create_scorecard_submission(**data)
            await self.session.commit()
            
            # Fetch complete submission details
            from app.models.recruitment import ScorecardSubmission
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            result = await self.session.execute(
                select(ScorecardSubmission).where(ScorecardSubmission.id == submission.id).options(selectinload(ScorecardSubmission.submitter))
            )
            return ScorecardSubmissionResponse.model_validate(result.scalar_one())
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def get_scorecards_for_round(self, round_uuid: uuid.UUID) -> list[ScorecardSubmissionResponse]:
        subs = await self.repo.get_scorecard_submissions_for_round(round_uuid)
        return [ScorecardSubmissionResponse.model_validate(s) for s in subs]

    # ------------------------------------------------------------------
    # Automation Rule Execution
    # ------------------------------------------------------------------

    async def create_automation_rule(self, payload: RecruitmentAutomationRuleCreate) -> RecruitmentAutomationRuleResponse:
        try:
            rule = await self.repo.create_automation_rule(**payload.model_dump())
            await self.session.commit()
            return RecruitmentAutomationRuleResponse.model_validate(rule)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    async def list_automation_rules(self, active_only: bool) -> list[RecruitmentAutomationRuleResponse]:
        rules = await self.repo.list_automation_rules(active_only)
        return [RecruitmentAutomationRuleResponse.model_validate(r) for r in rules]

    # ------------------------------------------------------------------
    # Notifications Feed
    # ------------------------------------------------------------------

    async def list_notifications(self, user_uuid: uuid.UUID, limit: int = 50) -> list[RecruitmentNotificationResponse]:
        notifs = await self.repo.list_recruitment_notifications(user_uuid, limit)
        return [RecruitmentNotificationResponse.model_validate(n) for n in notifs]

    async def mark_notification_read(self, notif_uuid: uuid.UUID) -> None:
        try:
            await self.repo.mark_notification_read(notif_uuid)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Offers Pagination
    # ------------------------------------------------------------------

    async def list_offers(self, page: int, limit: int) -> dict:
        try:
            offset = (page - 1) * limit
            offers = await self.repo.list_offers(limit=limit, offset=offset)
            total = await self.repo.count_offers()
            items = [OfferResponse.model_validate(o) for o in offers]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}
        except SQLAlchemyError as exc:
            logger.exception("list_offers: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Analytical aggregation queries (Phase 3 task)
    # ------------------------------------------------------------------

    async def get_recruitment_analytics(self, company_id: uuid.UUID | None = None) -> dict:
        try:
            from app.models.recruitment import Application, Job
            from sqlalchemy import select, func, or_

            stmt = select(Application.status, func.count(Application.id))
            if company_id:
                stmt = stmt.where(
                    or_(
                        Application.company_id == company_id,
                        Application.job_id.in_(select(Job.id).where(Job.company_id == company_id)),
                    )
                )
            stmt = stmt.group_by(Application.status)

            result = await self.session.execute(stmt)
            funnel_map = {row[0].lower(): row[1] for row in result.all()}

            return {
                "funnel": [
                    {"stage": "applied", "count": funnel_map.get("applied", 0)},
                    {"stage": "screening", "count": funnel_map.get("under_review", 0)},
                    {"stage": "assessment", "count": funnel_map.get("shortlisted", 0)},
                    {"stage": "interview", "count": funnel_map.get("interview_scheduled", 0)},
                    {"stage": "technical", "count": funnel_map.get("interview_completed", 0)},
                    {"stage": "hr", "count": funnel_map.get("selected", 0)},
                    {"stage": "offer", "count": funnel_map.get("offer_sent", 0)},
                    {"stage": "hired", "count": funnel_map.get("offer_accepted", 0) + funnel_map.get("employee_created", 0)},
                ],
            }
        except SQLAlchemyError as exc:
            logger.exception("get_recruitment_analytics: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Import/Export candidates/jobs
    # ------------------------------------------------------------------

    async def import_candidates_csv(self, file_content: str) -> int:
        from decimal import Decimal
        import csv
        import io
        count = 0
        try:
            f = io.StringIO(file_content)
            reader = csv.DictReader(f)
            for row in reader:
                await self.repo.create_candidate(
                    first_name=row.get("first_name", "First"),
                    last_name=row.get("last_name", "Last"),
                    email=row.get("email", ""),
                    phone=row.get("phone", ""),
                    location=row.get("location", ""),
                    skills=row.get("skills", "").split(","),
                    tags=row.get("tags", "").split(","),
                    years_experience=Decimal(row.get("years_experience", "0.0")),
                    source=row.get("source", "DIRECT"),
                    is_talent_pool=True,
                )
                count += 1
            await self.session.commit()
            return count
        except Exception as exc:
            await self.session.rollback()
            logger.error("import_candidates_csv failed: %s", exc)
            raise AppException(message="Failed to parse CSV file content.", status_code=status.HTTP_400_BAD_REQUEST)

    async def export_candidates_csv(self) -> str:
        import csv
        import io
        cands = await self.repo.list_candidates(limit=1000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "First Name", "Last Name", "Email", "Phone", "Location", "Experience", "Source"])
        for c in cands:
            writer.writerow([str(c.id), c.first_name, c.last_name, c.email, c.phone, c.location, str(c.years_experience), c.source])
        return output.getvalue()

    async def bulk_move_applications(self, application_ids: list[uuid.UUID], new_status: str) -> None:
        try:
            from sqlalchemy import update
            from app.models.recruitment import Application
            await self.session.execute(
                update(Application).where(Application.id.in_(application_ids)).values(status=new_status.upper())
            )
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("bulk_move_applications: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def bulk_tag_candidates(self, candidate_ids: list[uuid.UUID], tags: list[str]) -> None:
        try:
            for cid in candidate_ids:
                cand = await self.repo.get_candidate_by_id(cid)
                if cand:
                    existing = cand.tags or []
                    updated = list(set(existing + tags))
                    await self.repo.update_candidate(cid, tags=updated)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("bulk_tag_candidates: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_job_publish_channels(self, job_uuid: uuid.UUID) -> list[JobPublishResponse]:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import select
        from app.schemas.recruitment import JobPublishResponse

        job = await self.repo.get_job_by_id(job_uuid)
        if not job:
            raise AppException(message="Job not found.", status_code=status.HTTP_404_NOT_FOUND)

        stmt = select(JobPublishChannel).where(JobPublishChannel.job_id == job_uuid)
        res = await self.session.execute(stmt)
        db_channels = res.scalars().all()

        channel_map = {c.channel_name: c for c in db_channels}
        supported = ["career_site", "public_link", "internal_portal"]
        results = []

        frontend_base = "http://localhost:8080"
        
        for name in supported:
            chan = channel_map.get(name)
            if not chan:
                ukey = uuid.uuid4().hex[:8]
                chan = JobPublishChannel(
                    job_id=job_uuid,
                    channel_name=name,
                    is_active=False,
                    unique_key=ukey,
                )
                self.session.add(chan)
                await self.session.flush()
                await self.session.refresh(chan)

            url = None
            if chan.is_active:
                if name == "career_site":
                    url = f"{frontend_base}/careers/{job.slug}"
                elif name == "public_link":
                    url = f"{frontend_base}/jobs/apply/{chan.unique_key}"
                elif name == "internal_portal":
                    url = f"{frontend_base}/internal/jobs/{chan.unique_key}"

            results.append(JobPublishResponse(
                channel_name=chan.channel_name,
                is_active=chan.is_active,
                published_at=chan.published_at,
                updated_at=chan.updated_at,
                unique_key=chan.unique_key,
                url=url
            ))
        
        await self.session.commit()
        return results

    async def publish_job_channel(self, job_uuid: uuid.UUID, channel_name: str, is_active: bool) -> JobPublishResponse:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import select, and_
        from app.schemas.recruitment import JobPublishResponse
        
        job = await self.repo.get_job_by_id(job_uuid)
        if not job:
            raise AppException(message="Job not found.", status_code=status.HTTP_404_NOT_FOUND)

        stmt = select(JobPublishChannel).where(
            and_(JobPublishChannel.job_id == job_uuid, JobPublishChannel.channel_name == channel_name)
        )
        res = await self.session.execute(stmt)
        chan = res.scalar_one_or_none()

        if not chan:
            ukey = uuid.uuid4().hex[:8]
            chan = JobPublishChannel(
                job_id=job_uuid,
                channel_name=channel_name,
                is_active=is_active,
                unique_key=ukey,
                published_at=datetime.now(timezone.utc) if is_active else None
            )
            self.session.add(chan)
        else:
            chan.is_active = is_active
            if is_active and not chan.published_at:
                chan.published_at = datetime.now(timezone.utc)
            elif not is_active:
                chan.published_at = None
        
        await self.session.flush()
        await self.session.refresh(chan)
        
        frontend_base = "http://localhost:8080"
        url = None
        if chan.is_active:
            if channel_name == "career_site":
                url = f"{frontend_base}/careers/{job.slug}"
            elif channel_name == "public_link":
                url = f"{frontend_base}/jobs/apply/{chan.unique_key}"
            elif channel_name == "internal_portal":
                url = f"{frontend_base}/internal/jobs/{chan.unique_key}"

        resp = JobPublishResponse(
            channel_name=chan.channel_name,
            is_active=chan.is_active,
            published_at=chan.published_at,
            updated_at=chan.updated_at,
            unique_key=chan.unique_key,
            url=url
        )
        await self.session.commit()
        return resp

    async def get_or_create_sourcing_link(self, job_uuid: uuid.UUID) -> str:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import select, and_

        job = await self.repo.get_job_by_id(job_uuid)
        if not job:
            raise AppException(message="Job not found.", status_code=status.HTTP_404_NOT_FOUND)

        stmt = select(JobPublishChannel).where(
            and_(JobPublishChannel.job_id == job_uuid, JobPublishChannel.channel_name == "public_link")
        )
        res = await self.session.execute(stmt)
        chan = res.scalar_one_or_none()

        frontend_base = "http://localhost:8080"
        if not chan:
            ukey = uuid.uuid4().hex[:8]
            chan = JobPublishChannel(
                job_id=job_uuid,
                channel_name="public_link",
                is_active=True,
                unique_key=ukey,
                published_at=datetime.now(timezone.utc)
            )
            self.session.add(chan)
            await self.session.commit()
            return f"{frontend_base}/jobs/apply/{ukey}"
        else:
            ukey = chan.unique_key
            if not chan.is_active:
                chan.is_active = True
                chan.published_at = datetime.now(timezone.utc)
                await self.session.commit()
            return f"{frontend_base}/jobs/apply/{ukey}"

    async def close_job_position(self, job_uuid: uuid.UUID) -> None:
        from app.models.recruitment import JobPublishChannel
        from sqlalchemy import update
        
        job = await self.repo.get_job_by_id(job_uuid)
        if not job:
            raise AppException(message="Job not found.", status_code=status.HTTP_404_NOT_FOUND)

        job.status = "CLOSED"
        
        stmt = update(JobPublishChannel).where(JobPublishChannel.job_id == job_uuid).values(
            is_active=False,
            published_at=None
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def duplicate_job_custom(self, user_id: uuid.UUID, job_uuid: uuid.UUID, custom_data: JobDuplicateRequest) -> JobResponse:
        job = await self.repo.get_job_by_id(job_uuid)
        if not job:
            raise AppException(message="Job posting not found.", status_code=status.HTTP_404_NOT_FOUND)

        title = custom_data.title if custom_data.title else job.title + " (Copy)"
        location = custom_data.location if custom_data.location else job.location
        vacancies = custom_data.vacancies if custom_data.vacancies is not None else job.vacancies
        min_salary = custom_data.min_salary if custom_data.min_salary is not None else job.min_salary
        max_salary = custom_data.max_salary if custom_data.max_salary is not None else job.max_salary

        slug = await generate_job_slug(title, self.repo)
        new_job = await self.repo.create_job(
            title=title,
            slug=slug,
            department=job.department,
            designation=job.designation,
            employment_type=job.employment_type,
            experience_required=job.experience_required,
            min_experience=job.min_experience,
            max_experience=job.max_experience,
            min_salary=min_salary,
            max_salary=max_salary,
            location=location,
            vacancies=vacancies,
            job_description=job.job_description,
            responsibilities=job.responsibilities,
            requirements=job.requirements,
            benefits=job.benefits,
            interview_process_description=job.interview_process_description,
            status="DRAFT",
            created_by=user_id,
        )
        for skill in job.skills:
            await self.repo.add_job_skill(new_job.id, skill.skill_name)
        await self.session.commit()
        full_job = await self.repo.get_job_by_id(new_job.id)
        return JobResponse.model_validate(full_job)

    # ------------------------------------------------------------------
    # ATS Pipeline Integration
    # ------------------------------------------------------------------

    async def get_ats_pipeline_candidates(
        self,
        search: str | None = None,
        stage: str | None = None,
        status_filter: str | None = None,
        department: str | None = None,
        page: int = 1,
        limit: int = 20,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Fetch paginated list of ATS candidate pipeline records."""
        from app.repositories.ai_recruitment_repository import AIRecruitmentRepository
        ai_repo = AIRecruitmentRepository(self.session)
        offset = (page - 1) * limit
        candidates, total = await ai_repo.list_candidates(
            search=search,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
            company_id=company_id,
        )

        items = []
        for c in candidates:
            raw_status = (c.get("status") or "APPLIED").upper()
            cand_stage = "Applied"
            if raw_status in {"UNDER_REVIEW", "SCREENING"}:
                cand_stage = "Screening"
            elif raw_status in {"SHORTLISTED", "ASSESSMENT"}:
                cand_stage = "Shortlisted"
            elif raw_status in {"INTERVIEW_SCHEDULED", "INTERVIEW"}:
                cand_stage = "Interview"
            elif raw_status in {"INTERVIEW_COMPLETED", "TECHNICAL"}:
                cand_stage = "Technical"
            elif raw_status in {"SELECTED", "HR"}:
                cand_stage = "HR"
            elif raw_status in {"OFFER_SENT", "OFFER"}:
                cand_stage = "Offer"
            elif raw_status in {"OFFER_ACCEPTED", "EMPLOYEE_CREATED", "HIRED"}:
                cand_stage = "Hired"

            if stage and cand_stage.lower() != stage.lower():
                continue
            if department and c.get("department") and department.lower() not in c["department"].lower():
                continue

            c["stage"] = cand_stage
            items.append(c)

        return {
            "items": items,
            "total": len(items) if (stage or department) else total,
            "page": page,
            "limit": limit,
        }

    async def get_ats_pipeline_board(
        self,
        search: str | None = None,
        department: str | None = None,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Fetch ATS hiring pipeline board grouped by hiring stages."""
        from app.repositories.ai_recruitment_repository import AIRecruitmentRepository
        ai_repo = AIRecruitmentRepository(self.session)
        candidates, total = await ai_repo.list_candidates(
            search=search,
            limit=500,
            offset=0,
            company_id=company_id,
        )

        stages_map = {
            "Applied": [],
            "Screening": [],
            "Shortlisted": [],
            "Interview": [],
            "Technical": [],
            "HR": [],
            "Offer": [],
            "Hired": [],
        }

        for c in candidates:
            raw_status = (c.get("status") or "APPLIED").upper()
            cand_stage = "Applied"
            if raw_status in {"UNDER_REVIEW", "SCREENING"}:
                cand_stage = "Screening"
            elif raw_status in {"SHORTLISTED", "ASSESSMENT"}:
                cand_stage = "Shortlisted"
            elif raw_status in {"INTERVIEW_SCHEDULED", "INTERVIEW"}:
                cand_stage = "Interview"
            elif raw_status in {"INTERVIEW_COMPLETED", "TECHNICAL"}:
                cand_stage = "Technical"
            elif raw_status in {"SELECTED", "HR"}:
                cand_stage = "HR"
            elif raw_status in {"OFFER_SENT", "OFFER"}:
                cand_stage = "Offer"
            elif raw_status in {"OFFER_ACCEPTED", "EMPLOYEE_CREATED", "HIRED"}:
                cand_stage = "Hired"

            c["stage"] = cand_stage
            if cand_stage in stages_map:
                stages_map[cand_stage].append(c)
            else:
                stages_map["Applied"].append(c)

        board = [
            {"stage": stg_name, "count": len(stg_items), "candidates": stg_items}
            for stg_name, stg_items in stages_map.items()
        ]

        return {
            "stages": board,
            "total_candidates": total,
        }


async def get_recruitment_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
) -> RecruitmentService:
    return RecruitmentService(
        session=session,
        repo=RecruitmentRepository(session),
        auth_repo=AuthRepository(session),
        employee_repo=EmployeeRepository(session),
        email_service=email_service,
    )
