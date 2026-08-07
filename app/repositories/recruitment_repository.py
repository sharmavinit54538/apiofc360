"""Recruitment repository layer: direct database operations for the Recruitment module."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.recruitment import (
    Job,
    JobSkill,
    Application,
    ApplicationDocument,
    Interview,
    InterviewRound,
    InterviewSchedule,
    Offer,
    OfferDocument,
    CareerPageSetting,
    Candidate,
    JobRequisition,
    RecruitmentVendor,
    ScorecardTemplate,
    ScorecardSubmission,
    CandidateReferral,
    RecruitmentAutomationRule,
    CandidateCrmNote,
    RecruitmentNotification,
)

logger = logging.getLogger(__name__)


class RecruitmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active_job_filter(self):
        return Job.is_deleted == False  # noqa: E712

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    async def create_job(self, **kwargs: Any) -> Job:
        job = Job(**kwargs)
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job_by_id(self, job_uuid: uuid.UUID) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(and_(Job.id == job_uuid, self._active_job_filter()))
            .options(selectinload(Job.skills))
        )
        return result.scalar_one_or_none()

    async def get_job_by_slug(self, slug: str) -> Job | None:
        try:
            job_uuid = uuid.UUID(slug)
            result = await self.session.execute(
                select(Job)
                .where(and_(Job.id == job_uuid, self._active_job_filter(), Job.status == "PUBLISHED"))
                .options(selectinload(Job.skills))
            )
            job = result.scalar_one_or_none()
            if job:
                return job
        except (ValueError, AttributeError):
            pass

        result = await self.session.execute(
            select(Job)
            .where(and_(Job.slug == slug.lower(), self._active_job_filter(), Job.status == "PUBLISHED"))
            .options(selectinload(Job.skills))
        )
        return result.scalar_one_or_none()

    async def get_job_by_slug_raw(self, slug: str) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(and_(Job.slug == slug.lower(), self._active_job_filter()))
            .options(selectinload(Job.skills))
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        status: str | None = None,
        search: str | None = None,
        department: str | None = None,
        location: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Job]:
        stmt = select(Job).where(self._active_job_filter()).options(selectinload(Job.skills))

        if status:
            stmt = stmt.where(Job.status == status.upper())
        if department:
            stmt = stmt.where(Job.department.ilike(f"%{department}%"))
        if location:
            stmt = stmt.where(Job.location.ilike(f"%{location}%"))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Job.title.ilike(pattern),
                    Job.department.ilike(pattern),
                )
            )

        stmt = stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_jobs(
        self,
        status: str | None = None,
        search: str | None = None,
        department: str | None = None,
        location: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Job).where(self._active_job_filter())

        if status:
            stmt = stmt.where(Job.status == status.upper())
        if department:
            stmt = stmt.where(Job.department.ilike(f"%{department}%"))
        if location:
            stmt = stmt.where(Job.location.ilike(f"%{location}%"))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Job.title.ilike(pattern),
                    Job.department.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_job(self, job_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Job).where(Job.id == job_uuid).values(**kwargs)
        )

    async def soft_delete_job(self, job_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(Job)
            .where(Job.id == job_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    async def add_job_skill(self, job_uuid: uuid.UUID, skill_name: str) -> JobSkill:
        skill = JobSkill(job_id=job_uuid, skill_name=skill_name.strip())
        self.session.add(skill)
        await self.session.flush()
        return skill

    async def clear_job_skills(self, job_uuid: uuid.UUID) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(JobSkill).where(JobSkill.job_id == job_uuid)
        )

    # ------------------------------------------------------------------
    # Application CRUD
    # ------------------------------------------------------------------

    async def create_application(self, **kwargs: Any) -> Application:
        app = Application(**kwargs)
        self.session.add(app)
        await self.session.flush()
        return app

    async def get_application_by_id(self, app_uuid: uuid.UUID) -> Application | None:
        result = await self.session.execute(
            select(Application)
            .where(Application.id == app_uuid)
            .options(
                selectinload(Application.documents),
                selectinload(Application.job),
                selectinload(Application.candidate),
            )
        )
        return result.scalar_one_or_none()

    async def list_applications(
        self,
        job_id: uuid.UUID | None = None,
        status: str | None = None,
        search: str | None = None,
        company_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Application]:
        stmt = select(Application).options(
            selectinload(Application.job),
            selectinload(Application.documents),
            selectinload(Application.candidate),
        )

        if company_id:
            stmt = stmt.where(
                or_(
                    Application.company_id == company_id,
                    Application.job.has(Job.company_id == company_id),
                    Application.company_id.is_(None),
                )
            )

        if job_id:
            stmt = stmt.where(Application.job_id == job_id)
        if status:
            stmt = stmt.where(Application.status == status.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Application.first_name.ilike(pattern),
                    Application.last_name.ilike(pattern),
                    Application.email.ilike(pattern),
                    Application.phone.ilike(pattern),
                )
            )

        stmt = stmt.order_by(Application.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_applications(
        self,
        job_id: uuid.UUID | None = None,
        status: str | None = None,
        search: str | None = None,
        company_id: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Application)

        if company_id:
            stmt = stmt.where(
                or_(
                    Application.company_id == company_id,
                    Application.job.has(Job.company_id == company_id),
                    Application.company_id.is_(None),
                )
            )

        if job_id:
            stmt = stmt.where(Application.job_id == job_id)
        if status:
            stmt = stmt.where(Application.status == status.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Application.first_name.ilike(pattern),
                    Application.last_name.ilike(pattern),
                    Application.email.ilike(pattern),
                    Application.phone.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_application_status(self, app_uuid: uuid.UUID, status: str) -> None:
        await self.session.execute(
            update(Application).where(Application.id == app_uuid).values(status=status.upper())
        )

    async def add_application_document(self, **kwargs: Any) -> ApplicationDocument:
        doc = ApplicationDocument(**kwargs)
        self.session.add(doc)
        await self.session.flush()
        return doc

    # ------------------------------------------------------------------
    # Interview Operations
    # ------------------------------------------------------------------

    async def create_interview(self, **kwargs: Any) -> Interview:
        obj = Interview(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_interview_by_id(self, int_uuid: uuid.UUID) -> Interview | None:
        result = await self.session.execute(
            select(Interview)
            .where(Interview.id == int_uuid)
            .options(
                selectinload(Interview.rounds),
                selectinload(Interview.schedules),
            )
        )
        return result.scalar_one_or_none()

    async def get_interview_by_application_id(self, app_uuid: uuid.UUID) -> Interview | None:
        result = await self.session.execute(
            select(Interview)
            .where(Interview.application_id == app_uuid)
            .options(
                selectinload(Interview.rounds),
                selectinload(Interview.schedules),
            )
        )
        return result.scalar_one_or_none()

    async def create_interview_round(self, **kwargs: Any) -> InterviewRound:
        obj = InterviewRound(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_interview_round_by_id(self, round_uuid: uuid.UUID) -> InterviewRound | None:
        result = await self.session.execute(
            select(InterviewRound).where(InterviewRound.id == round_uuid)
        )
        return result.scalar_one_or_none()

    async def update_interview_round(self, round_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(InterviewRound).where(InterviewRound.id == round_uuid).values(**kwargs)
        )

    async def update_interview_status(self, int_uuid: uuid.UUID, status: str, current_round_index: int | None = None) -> None:
        vals = {"status": status.upper()}
        if current_round_index is not None:
            vals["current_round_index"] = current_round_index
        await self.session.execute(
            update(Interview).where(Interview.id == int_uuid).values(**vals)
        )

    # ------------------------------------------------------------------
    # Interview Scheduling (limited to next 7 days, double book check)
    # ------------------------------------------------------------------

    async def check_double_booking(self, check_date: date, check_time: Any) -> bool:
        """Return True if a slot is already booked for this date and time."""
        result = await self.session.execute(
            select(InterviewSchedule).where(
                and_(
                    InterviewSchedule.interview_date == check_date,
                    InterviewSchedule.interview_time == check_time,
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_interview_schedule(self, **kwargs: Any) -> InterviewSchedule:
        obj = InterviewSchedule(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_interviews(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Interview]:
        stmt = select(Interview).options(
            selectinload(Interview.rounds),
            selectinload(Interview.schedules),
        )
        if status:
            stmt = stmt.where(Interview.status == status.upper())
        stmt = stmt.order_by(Interview.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_interviews(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Interview)
        if status:
            stmt = stmt.where(Interview.status == status.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Offer Management
    # ------------------------------------------------------------------

    async def create_offer(self, **kwargs: Any) -> Offer:
        obj = Offer(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_offer_by_id(self, offer_uuid: uuid.UUID) -> Offer | None:
        result = await self.session.execute(
            select(Offer)
            .where(Offer.id == offer_uuid)
            .options(
                selectinload(Offer.documents),
                selectinload(Offer.application),
            )
        )
        return result.scalar_one_or_none()

    async def get_offer_by_application_id(self, app_uuid: uuid.UUID) -> Offer | None:
        result = await self.session.execute(
            select(Offer)
            .where(Offer.application_id == app_uuid)
            .options(
                selectinload(Offer.documents),
                selectinload(Offer.application),
            )
        )
        return result.scalar_one_or_none()

    async def update_offer_status(self, offer_uuid: uuid.UUID, status: str) -> None:
        await self.session.execute(
            update(Offer).where(Offer.id == offer_uuid).values(status=status.upper())
        )

    async def create_offer_document(self, **kwargs: Any) -> OfferDocument:
        obj = OfferDocument(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Dashboard Metrics
    # ------------------------------------------------------------------

    async def get_dashboard_metrics(self, company_id: uuid.UUID | None = None) -> dict[str, int]:
        import asyncio
        from sqlalchemy import case, cast, Date

        today = date.today()

        # 1. Job metrics (single pass)
        job_filter = [self._active_job_filter()]
        if company_id:
            job_filter.append(Job.company_id == company_id)

        stmt_jobs = select(
            func.count(Job.id).label("total_jobs"),
            func.count(case((Job.status == "PUBLISHED", 1))).label("published_jobs"),
            func.count(case((Job.status == "DRAFT", 1))).label("draft_jobs"),
            func.count(case((Job.status == "CLOSED", 1))).label("closed_jobs"),
        ).where(and_(*job_filter))

        # 2. Application metrics (single pass)
        app_filter = []
        if company_id:
            app_filter.append(
                or_(
                    Application.company_id == company_id,
                    Application.job_id.in_(select(Job.id).where(Job.company_id == company_id)),
                )
            )

        stmt_apps = select(
            func.count(Application.id).label("total_applications"),
            func.count(case((cast(Application.created_at, Date) == today, 1))).label("applications_today"),
            func.count(case((Application.status == "SHORTLISTED", 1))).label("shortlisted_applications"),
            func.count(case((Application.status == "REJECTED", 1))).label("rejected_applications"),
            func.count(case((Application.status == "EMPLOYEE_CREATED", 1))).label("employees_hired"),
        )
        if app_filter:
            stmt_apps = stmt_apps.where(and_(*app_filter))

        # 3. Interview metrics
        int_filter = [Interview.status == "SCHEDULED"]
        if company_id:
            int_filter.append(Interview.company_id == company_id)
        stmt_interviews = select(func.count(Interview.id)).where(and_(*int_filter))

        # 4. Offer metrics (single pass)
        off_filter = []
        if company_id:
            off_filter.append(Offer.company_id == company_id)
        stmt_offers = select(
            func.count(case((Offer.status == "SENT", 1))).label("offers_sent"),
            func.count(case((Offer.status == "ACCEPTED", 1))).label("offers_accepted"),
        )
        if off_filter:
            stmt_offers = stmt_offers.where(and_(*off_filter))

        # Execute queries sequentially on the single session
        job_res = await self.session.execute(stmt_jobs)
        app_res = await self.session.execute(stmt_apps)
        int_res = await self.session.execute(stmt_interviews)
        off_res = await self.session.execute(stmt_offers)

        job_row = job_res.one()
        app_row = app_res.one()
        int_val = int_res.scalar() or 0
        off_row = off_res.one()

        return {
            "total_jobs": job_row.total_jobs or 0,
            "published_jobs": job_row.published_jobs or 0,
            "draft_jobs": job_row.draft_jobs or 0,
            "closed_jobs": job_row.closed_jobs or 0,
            "total_applications": app_row.total_applications or 0,
            "applications_today": app_row.applications_today or 0,
            "shortlisted_count": app_row.shortlisted_applications or 0,
            "rejected_count": app_row.rejected_applications or 0,
            "interviews_scheduled_count": int_val,
            "offers_sent_count": off_row.offers_sent or 0,
            "offers_accepted_count": off_row.offers_accepted or 0,
            "employees_hired_count": app_row.employees_hired or 0,
        }

    # ------------------------------------------------------------------
    # Candidate CRUD
    # ------------------------------------------------------------------

    async def create_candidate(self, **kwargs: Any) -> Candidate:
        obj = Candidate(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_candidate_by_id(self, candidate_uuid: uuid.UUID) -> Candidate | None:
        result = await self.session.execute(
            select(Candidate)
            .where(Candidate.id == candidate_uuid)
            .options(
                selectinload(Candidate.applications).selectinload(Application.job),
                selectinload(Candidate.notes).selectinload(CandidateCrmNote.author),
                selectinload(Candidate.vendor),
            )
        )
        return result.scalar_one_or_none()

    async def get_candidate_by_email(self, email: str) -> Candidate | None:
        result = await self.session.execute(
            select(Candidate).where(Candidate.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def list_candidates(
        self,
        is_talent_pool: bool | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
        company_id: uuid.UUID | None = None,
    ) -> list[Candidate]:
        stmt = select(Candidate).options(
            selectinload(Candidate.applications).selectinload(Application.job)
        )
        if company_id:
            stmt = stmt.where(
                or_(
                    Candidate.applications.any(Application.company_id == company_id),
                    Candidate.applications.any(
                        Application.job_id.in_(select(Job.id).where(Job.company_id == company_id))
                    ),
                    ~Candidate.applications.any(),
                )
            )
        if is_talent_pool is not None:
            stmt = stmt.where(Candidate.is_talent_pool == is_talent_pool)
        if tag:
            stmt = stmt.where(
                or_(
                    Candidate.tags.contains([tag]),
                    Candidate.skills.contains([tag])
                )
            )
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Candidate.first_name.ilike(pattern),
                    Candidate.last_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    Candidate.phone.ilike(pattern),
                    Candidate.location.ilike(pattern),
                    Candidate.applications.any(
                        Application.job_id.in_(
                            select(Job.id).where(
                                or_(
                                    Job.title.ilike(pattern),
                                    Job.department.ilike(pattern),
                                )
                            )
                        )
                    ),
                )
            )
        stmt = stmt.order_by(Candidate.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_candidates(
        self,
        is_talent_pool: bool | None = None,
        search: str | None = None,
        tag: str | None = None,
        company_id: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Candidate)
        if company_id:
            stmt = stmt.where(
                or_(
                    Candidate.applications.any(Application.company_id == company_id),
                    Candidate.applications.any(
                        Application.job_id.in_(select(Job.id).where(Job.company_id == company_id))
                    ),
                    ~Candidate.applications.any(),
                )
            )
        if is_talent_pool is not None:
            stmt = stmt.where(Candidate.is_talent_pool == is_talent_pool)
        if tag:
            stmt = stmt.where(
                or_(
                    Candidate.tags.contains([tag]),
                    Candidate.skills.contains([tag])
                )
            )
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Candidate.first_name.ilike(pattern),
                    Candidate.last_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    Candidate.location.ilike(pattern),
                )
            )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_candidate(self, candidate_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Candidate).where(Candidate.id == candidate_uuid).values(**kwargs)
        )

    async def delete_candidate(self, candidate_uuid: uuid.UUID) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(Candidate).where(Candidate.id == candidate_uuid)
        )

    # ------------------------------------------------------------------
    # Job Requisitions CRUD
    # ------------------------------------------------------------------

    async def create_requisition(self, **kwargs: Any) -> JobRequisition:
        obj = JobRequisition(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_requisition_by_id(self, req_uuid: uuid.UUID) -> JobRequisition | None:
        result = await self.session.execute(
            select(JobRequisition)
            .where(JobRequisition.id == req_uuid)
            .options(
                selectinload(JobRequisition.requester),
                selectinload(JobRequisition.approver),
            )
        )
        return result.scalar_one_or_none()

    async def list_requisitions(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRequisition]:
        stmt = select(JobRequisition).options(
            selectinload(JobRequisition.requester),
            selectinload(JobRequisition.approver),
        )
        if status:
            stmt = stmt.where(JobRequisition.status == status.upper())
        stmt = stmt.order_by(JobRequisition.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_requisitions(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(JobRequisition)
        if status:
            stmt = stmt.where(JobRequisition.status == status.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_requisition_status(
        self, req_uuid: uuid.UUID, status: str, approved_by: uuid.UUID | None = None
    ) -> None:
        vals = {"status": status.upper()}
        if approved_by:
            vals["approved_by"] = approved_by
        await self.session.execute(
            update(JobRequisition).where(JobRequisition.id == req_uuid).values(**vals)
        )

    # ------------------------------------------------------------------
    # Recruitment Vendors CRUD
    # ------------------------------------------------------------------

    async def create_vendor(self, **kwargs: Any) -> RecruitmentVendor:
        obj = RecruitmentVendor(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_vendor_by_id(self, vendor_uuid: uuid.UUID) -> RecruitmentVendor | None:
        result = await self.session.execute(
            select(RecruitmentVendor).where(RecruitmentVendor.id == vendor_uuid)
        )
        return result.scalar_one_or_none()

    async def list_vendors(self, limit: int = 50, offset: int = 0) -> list[RecruitmentVendor]:
        stmt = select(RecruitmentVendor).order_by(RecruitmentVendor.name.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_vendors(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(RecruitmentVendor))
        return result.scalar_one()

    async def update_vendor(self, vendor_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(RecruitmentVendor).where(RecruitmentVendor.id == vendor_uuid).values(**kwargs)
        )

    async def delete_vendor(self, vendor_uuid: uuid.UUID) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(RecruitmentVendor).where(RecruitmentVendor.id == vendor_uuid)
        )

    # ------------------------------------------------------------------
    # Scorecards CRUD
    # ------------------------------------------------------------------

    async def create_scorecard_template(self, **kwargs: Any) -> ScorecardTemplate:
        obj = ScorecardTemplate(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_scorecard_template_by_id(self, template_uuid: uuid.UUID) -> ScorecardTemplate | None:
        result = await self.session.execute(
            select(ScorecardTemplate).where(ScorecardTemplate.id == template_uuid)
        )
        return result.scalar_one_or_none()

    async def list_scorecard_templates(self, department: str | None = None) -> list[ScorecardTemplate]:
        stmt = select(ScorecardTemplate)
        if department:
            stmt = stmt.where(ScorecardTemplate.department.ilike(f"%{department}%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_scorecard_submission(self, **kwargs: Any) -> ScorecardSubmission:
        obj = ScorecardSubmission(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_scorecard_submissions_for_round(self, round_uuid: uuid.UUID) -> list[ScorecardSubmission]:
        result = await self.session.execute(
            select(ScorecardSubmission)
            .where(ScorecardSubmission.interview_round_id == round_uuid)
            .options(selectinload(ScorecardSubmission.submitter))
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Referrals CRUD
    # ------------------------------------------------------------------

    async def create_referral(self, **kwargs: Any) -> CandidateReferral:
        obj = CandidateReferral(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_referral_by_id(self, referral_uuid: uuid.UUID) -> CandidateReferral | None:
        result = await self.session.execute(
            select(CandidateReferral)
            .where(CandidateReferral.id == referral_uuid)
            .options(
                selectinload(CandidateReferral.candidate),
                selectinload(CandidateReferral.employee),
                selectinload(CandidateReferral.job),
            )
        )
        return result.scalar_one_or_none()

    async def list_referrals(self, limit: int = 50, offset: int = 0) -> list[CandidateReferral]:
        stmt = select(CandidateReferral).options(
            selectinload(CandidateReferral.candidate),
            selectinload(CandidateReferral.employee),
            selectinload(CandidateReferral.job),
        ).order_by(CandidateReferral.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_referrals(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(CandidateReferral))
        return result.scalar_one()

    async def update_referral_status(self, referral_uuid: uuid.UUID, status: str, reward_status: str | None = None) -> None:
        vals = {"status": status.upper()}
        if reward_status:
            vals["reward_status"] = reward_status.upper()
        await self.session.execute(
            update(CandidateReferral).where(CandidateReferral.id == referral_uuid).values(**vals)
        )

    # ------------------------------------------------------------------
    # Automations CRUD
    # ------------------------------------------------------------------

    async def create_automation_rule(self, **kwargs: Any) -> RecruitmentAutomationRule:
        obj = RecruitmentAutomationRule(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_automation_rules(self, active_only: bool = False) -> list[RecruitmentAutomationRule]:
        stmt = select(RecruitmentAutomationRule)
        if active_only:
            stmt = stmt.where(RecruitmentAutomationRule.is_active == True)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_automation_rule(self, rule_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(RecruitmentAutomationRule).where(RecruitmentAutomationRule.id == rule_uuid).values(**kwargs)
        )

    # ------------------------------------------------------------------
    # CRM Notes CRUD
    # ------------------------------------------------------------------

    async def create_crm_note(self, **kwargs: Any) -> CandidateCrmNote:
        obj = CandidateCrmNote(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_crm_notes_for_candidate(self, candidate_uuid: uuid.UUID) -> list[CandidateCrmNote]:
        result = await self.session.execute(
            select(CandidateCrmNote)
            .where(CandidateCrmNote.candidate_id == candidate_uuid)
            .options(selectinload(CandidateCrmNote.author))
            .order_by(CandidateCrmNote.created_at.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Recruitment Notifications CRUD
    # ------------------------------------------------------------------

    async def create_recruitment_notification(self, **kwargs: Any) -> RecruitmentNotification:
        obj = RecruitmentNotification(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_recruitment_notifications(self, user_uuid: uuid.UUID, limit: int = 50) -> list[RecruitmentNotification]:
        result = await self.session.execute(
            select(RecruitmentNotification)
            .where(RecruitmentNotification.user_id == user_uuid)
            .order_by(RecruitmentNotification.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_notification_read(self, notif_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(RecruitmentNotification)
            .where(RecruitmentNotification.id == notif_uuid)
            .values(is_read=True)
        )

    # ------------------------------------------------------------------
    # Offers List CRUD
    # ------------------------------------------------------------------

    async def list_offers(self, limit: int = 50, offset: int = 0) -> list[Offer]:
        stmt = select(Offer).options(
            selectinload(Offer.application),
            selectinload(Offer.documents),
        ).order_by(Offer.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_offers(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Offer))
        return result.scalar_one()
