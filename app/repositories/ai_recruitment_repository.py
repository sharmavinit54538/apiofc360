"""AI Recruitment Repository for database operations across candidates, resume docs, match scores, and screening results."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore, AIScreeningResult
from app.models.recruitment import Candidate, Job, Application

from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


class AIRecruitmentRepository:
    """Async repository for AI Resume Screening & ATS matching tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_job_by_id(self, job_id: uuid.UUID) -> Job | None:
        """Fetch Job by ID with eager loaded skills."""
        stmt = select(Job).options(selectinload(Job.skills)).where(Job.id == job_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_or_create_candidate(
        self,
        name: str,
        email: str | None,
        phone: str | None,
        company_id: uuid.UUID | None = None,
        current_company: str | None = None,
        current_role: str | None = None,
        years_experience: float = 0.0,
        skills: list[str] | None = None,
        location: str | None = None,
        resume_path: str | None = None,
        resume_name: str | None = None,
    ) -> Candidate:
        """Fetch existing candidate by email or create a new candidate record."""
        cand = None
        if email and email.strip():
            stmt = select(Candidate).where(Candidate.email.ilike(email.strip()))
            res = await self.session.execute(stmt)
            cand = res.scalar_one_or_none()

        if cand:
            # Update attributes if they were empty or provided freshly
            if current_company:
                cand.current_company = current_company
            if current_role:
                cand.current_role = current_role
            if years_experience > 0:
                cand.years_experience = years_experience
            if skills and hasattr(cand, "skills"):
                cand.skills = skills
            if location and (not cand.location or cand.location == "Default Location"):
                cand.location = location
            if resume_path:
                cand.resume_path = resume_path
            if resume_name:
                cand.resume_name = resume_name
            await self.session.commit()
            await self.session.refresh(cand)
        else:
            names = (name or "Candidate").split(" ")
            first_name = names[0]
            last_name = " ".join(names[1:]) if len(names) > 1 else ""

            cand = Candidate(
                first_name=first_name,
                last_name=last_name or "Candidate",
                email=email or f"candidate_{uuid.uuid4().hex[:8]}@example.com",
                phone=phone or "0000000000",
                location=location or "Default Location",
                years_experience=years_experience,
                current_company=current_company or "",
                current_role=current_role or "",
                skills=skills or [],
                resume_path=resume_path,
                resume_name=resume_name,
                source="AI Resume Upload",
                is_talent_pool=False,
            )
            self.session.add(cand)
            await self.session.commit()
            await self.session.refresh(cand)

        return cand

    async def create_resume_document(self, doc: AIResumeDocument) -> AIResumeDocument:
        """Save AIResumeDocument record."""
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def create_match_score(self, match_score: CandidateMatchScore) -> CandidateMatchScore:
        """Save CandidateMatchScore record."""
        self.session.add(match_score)
        await self.session.commit()
        await self.session.refresh(match_score)
        return match_score

    async def create_screening_result(self, screening: AIScreeningResult) -> AIScreeningResult:
        """Save AIScreeningResult record."""
        self.session.add(screening)
        await self.session.commit()
        await self.session.refresh(screening)
        return screening

    async def get_candidate_by_id(self, candidate_id: uuid.UUID) -> Candidate | None:
        """Fetch candidate by UUID."""
        stmt = select(Candidate).where(Candidate.id == candidate_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_resume_doc(self, candidate_id: uuid.UUID) -> AIResumeDocument | None:
        """Fetch latest resume document for candidate."""
        stmt = select(AIResumeDocument).where(AIResumeDocument.candidate_id == candidate_id).order_by(AIResumeDocument.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_match_score(self, resume_doc_id: uuid.UUID) -> CandidateMatchScore | None:
        """Fetch match score for resume doc."""
        stmt = select(CandidateMatchScore).where(CandidateMatchScore.resume_document_id == resume_doc_id).order_by(CandidateMatchScore.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_screening_result(self, resume_doc_id: uuid.UUID) -> AIScreeningResult | None:
        """Fetch screening result for resume doc."""
        stmt = select(AIScreeningResult).where(AIScreeningResult.resume_document_id == resume_doc_id).order_by(AIScreeningResult.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def list_candidates(
        self,
        search: str | None = None,
        status_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
        company_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[dict[str, Any]], int]:
        """Fetch paginated list of candidate profiles with latest ATS score & status."""
        stmt = select(Candidate)
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

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Candidate.first_name.ilike(pattern),
                    Candidate.last_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    Candidate.phone.ilike(pattern),
                    Candidate.current_role.ilike(pattern),
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

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        stmt = stmt.order_by(Candidate.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        candidates = res.scalars().all()

        results = []
        for idx, cand in enumerate(candidates, start=1):
            resume = await self.get_latest_resume_doc(cand.id)
            ats_score = 75.0
            match_tier = "Good Match"
            status = "APPLIED"
            resume_doc_id = None

            if resume:
                resume_doc_id = resume.id
                status = resume.parse_status
                ms = await self.get_match_score(resume.id)
                if ms:
                    ats_score = round(ms.overall_match_score * 100, 1) if ms.overall_match_score <= 1.0 else round(ms.overall_match_score, 1)
                    if ats_score >= 85:
                        match_tier = "Best Match"
                    elif ats_score >= 70:
                        match_tier = "Good Match"
                    elif ats_score >= 50:
                        match_tier = "Average Match"
                    else:
                        match_tier = "Low Match"

            # Fetch linked application if available (by candidate_id or matching email)
            app_conds = [Application.candidate_id == cand.id]
            if cand.email:
                app_conds.append(Application.email.ilike(cand.email.strip()))

            app_stmt = (
                select(Application)
                .options(selectinload(Application.job))
                .where(or_(*app_conds))
                .order_by(Application.created_at.desc())
                .limit(1)
            )
            app_res = await self.session.execute(app_stmt)
            app_rec = app_res.scalar_one_or_none()

            app_id = app_rec.id if app_rec else None
            job_id = app_rec.job_id if app_rec else None
            job_title = app_rec.job.title if (app_rec and app_rec.job) else None
            if app_rec and not resume:
                status = app_rec.status

            name = f"{cand.first_name} {cand.last_name}".strip()
            results.append({
                "id": cand.id,
                "candidate_id": cand.id,
                "resume_document_id": resume_doc_id,
                "application_id": app_id,
                "job_id": job_id,
                "job_title": job_title,
                "name": name,
                "first_name": cand.first_name,
                "last_name": cand.last_name,
                "email": cand.email,
                "phone": cand.phone,
                "location": cand.location,
                "current_company": cand.current_company,
                "current_role": cand.current_role,
                "years_experience": float(cand.years_experience or 0.0),
                "experience_years": float(cand.years_experience or 0.0),
                "ats_score": ats_score,
                "rank": idx + offset,
                "match_tier": match_tier,
                "status": status,
                "created_at": cand.created_at,
                "applied_at": app_rec.created_at if app_rec else cand.created_at,
            })

        return results, total
