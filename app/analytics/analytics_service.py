"""Recruitment Analytics Service.

Computes and returns key recruitment metrics:
- Hiring Funnel (applications → shortlisted → interviewed → offered → hired)
- Offer Acceptance Rate
- Interview Success Rate
- Time To Hire (average days from application to offer)
- Recruiter Performance (applications managed, hires closed)
- Source Performance (which channels bring best candidates)
- Candidate Conversion rates per stage
- Department-level analytics

All queries are async and PostgreSQL-native for performance at scale.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, case, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for computing recruitment analytics from the database."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_hiring_funnel(
        self,
        company_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute the hiring funnel — conversion at each stage."""
        from app.models.recruitment import Application

        filters = []
        if company_id:
            filters.append(Application.company_id == company_id)
        if date_from:
            filters.append(Application.created_at >= date_from)
        if date_to:
            filters.append(Application.created_at <= date_to)

        base_q = select(Application.status, func.count().label("count"))
        if filters:
            base_q = base_q.where(and_(*filters))
        base_q = base_q.group_by(Application.status)

        result = await self._db.execute(base_q)
        rows = result.all()

        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.status] = int(row.count)

        total = sum(status_counts.values())

        funnel_stages = [
            "APPLIED", "SHORTLISTED", "INTERVIEW_SCHEDULED",
            "INTERVIEW_COMPLETED", "OFFERED", "HIRED", "REJECTED",
        ]

        funnel: list[dict] = []
        for stage in funnel_stages:
            count = status_counts.get(stage, 0)
            funnel.append({
                "stage": stage,
                "count": count,
                "percentage": round(count / total * 100, 1) if total > 0 else 0.0,
            })

        return {
            "total_applications": total,
            "funnel": funnel,
            "period": {
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None,
            },
        }

    async def get_offer_acceptance_rate(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Compute offer acceptance rate over the past N days."""
        from app.models.recruitment import Offer

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        filters = [Offer.created_at >= since]
        if company_id:
            filters.append(Offer.company_id == company_id)

        q = select(Offer.status, func.count().label("count")).where(
            and_(*filters)
        ).group_by(Offer.status)

        result = await self._db.execute(q)
        status_counts: dict[str, int] = {row.status: row.count for row in result.all()}

        total_offers = sum(status_counts.values())
        accepted = status_counts.get("ACCEPTED", 0)
        declined = status_counts.get("DECLINED", 0) + status_counts.get("REJECTED", 0)

        rate = round(accepted / total_offers * 100, 1) if total_offers > 0 else 0.0

        return {
            "total_offers": total_offers,
            "accepted": accepted,
            "declined": declined,
            "pending": status_counts.get("SENT", 0),
            "acceptance_rate_pct": rate,
            "days_period": days,
        }

    async def get_time_to_hire(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Compute average time from application to offer."""
        from app.models.recruitment import Application, Offer

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        # Join applications with their offers
        q = (
            select(
                Application.created_at.label("applied_at"),
                Offer.created_at.label("offered_at"),
            )
            .join(Offer, Offer.application_id == Application.id)
            .where(Application.created_at >= since)
        )
        if company_id:
            q = q.where(Application.company_id == company_id)

        result = await self._db.execute(q)
        rows = result.all()

        if not rows:
            return {
                "avg_days": 0,
                "min_days": 0,
                "max_days": 0,
                "median_days": 0,
                "sample_size": 0,
                "days_period": days,
            }

        day_diffs = []
        for row in rows:
            if row.applied_at and row.offered_at:
                diff = (row.offered_at - row.applied_at).days
                if 0 <= diff <= 365:  # Sanity check
                    day_diffs.append(diff)

        if not day_diffs:
            return {"avg_days": 0, "min_days": 0, "max_days": 0, "median_days": 0,
                    "sample_size": 0, "days_period": days}

        day_diffs.sort()
        mid = len(day_diffs) // 2
        median = day_diffs[mid] if len(day_diffs) % 2 else (day_diffs[mid - 1] + day_diffs[mid]) / 2

        return {
            "avg_days": round(sum(day_diffs) / len(day_diffs), 1),
            "min_days": day_diffs[0],
            "max_days": day_diffs[-1],
            "median_days": median,
            "sample_size": len(day_diffs),
            "days_period": days,
        }

    async def get_source_performance(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Analyze which sourcing channels produce the best candidates."""
        from app.models.recruitment import Application, Candidate

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        q = (
            select(
                Candidate.source,
                func.count(Application.id).label("applications"),
                func.sum(
                    case((Application.status == "HIRED", 1), else_=0)
                ).label("hires"),
                func.sum(
                    case((Application.status == "SHORTLISTED", 1), else_=0)
                ).label("shortlisted"),
            )
            .join(Application, Application.candidate_id == Candidate.id)
            .where(Application.created_at >= since)
            .group_by(Candidate.source)
            .order_by(func.count(Application.id).desc())
        )

        if company_id:
            q = q.where(Application.company_id == company_id)

        result = await self._db.execute(q)
        rows = result.all()

        source_data = []
        for row in rows:
            apps = int(row.applications or 0)
            hires = int(row.hires or 0)
            shortlisted = int(row.shortlisted or 0)

            source_data.append({
                "source": row.source or "Unknown",
                "applications": apps,
                "shortlisted": shortlisted,
                "hires": hires,
                "hire_rate_pct": round(hires / apps * 100, 1) if apps > 0 else 0.0,
                "shortlist_rate_pct": round(shortlisted / apps * 100, 1) if apps > 0 else 0.0,
            })

        return source_data

    async def get_recruiter_performance(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Compute per-recruiter performance metrics."""
        from app.models.recruitment import Job
        from app.models.user import User

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        q = (
            select(
                User.id.label("user_id"),
                User.first_name,
                User.last_name,
                func.count(Job.id).label("jobs_created"),
            )
            .join(Job, Job.created_by == User.id)
            .where(Job.created_at >= since)
            .group_by(User.id, User.first_name, User.last_name)
            .order_by(func.count(Job.id).desc())
        )

        result = await self._db.execute(q)
        rows = result.all()

        return [
            {
                "recruiter_id": str(row.user_id),
                "recruiter_name": f"{row.first_name} {row.last_name}",
                "jobs_created": int(row.jobs_created or 0),
            }
            for row in rows
        ]

    async def get_department_analytics(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Compute per-department hiring analytics."""
        from app.models.recruitment import Job, Application

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        q = (
            select(
                Job.department,
                func.count(Job.id).label("open_positions"),
                func.count(Application.id).label("total_applications"),
                func.sum(
                    case((Application.status == "HIRED", 1), else_=0)
                ).label("hires"),
            )
            .join(Application, Application.job_id == Job.id, isouter=True)
            .where(Job.created_at >= since)
            .group_by(Job.department)
            .order_by(func.count(Application.id).desc())
        )

        if company_id:
            q = q.where(Job.company_id == company_id)

        result = await self._db.execute(q)
        rows = result.all()

        return [
            {
                "department": row.department or "Unknown",
                "open_positions": int(row.open_positions or 0),
                "total_applications": int(row.total_applications or 0),
                "hires": int(row.hires or 0),
                "fill_rate_pct": round(
                    int(row.hires or 0) / int(row.open_positions or 1) * 100, 1
                ),
            }
            for row in rows
        ]

    async def get_interview_success_rate(
        self,
        company_id: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Compute interview-to-offer conversion rate."""
        from app.models.recruitment import Interview, Application

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        q = (
            select(
                Interview.status,
                func.count().label("count"),
            )
            .join(Application, Application.id == Interview.application_id)
            .where(Interview.created_at >= since)
            .group_by(Interview.status)
        )
        if company_id:
            q = q.where(Interview.company_id == company_id)

        result = await self._db.execute(q)
        status_counts: dict[str, int] = {row.status: int(row.count) for row in result.all()}

        total = sum(status_counts.values())
        completed = status_counts.get("COMPLETED", 0)
        passed = status_counts.get("PASSED", 0)

        return {
            "total_interviews": total,
            "completed": completed,
            "passed": passed,
            "scheduled": status_counts.get("SCHEDULED", 0),
            "cancelled": status_counts.get("CANCELLED", 0),
            "completion_rate_pct": round(completed / total * 100, 1) if total > 0 else 0.0,
            "pass_rate_pct": round(passed / completed * 100, 1) if completed > 0 else 0.0,
            "days_period": days,
        }

    async def get_dashboard_summary(
        self,
        company_id: str | None = None,
    ) -> dict[str, Any]:
        """Get a high-level recruitment dashboard summary."""
        from app.models.recruitment import Application, Job, Candidate

        # Total active jobs
        jobs_q = select(func.count()).select_from(Job).where(Job.status == "OPEN")
        if company_id:
            jobs_q = jobs_q.where(Job.company_id == company_id)

        total_jobs = (await self._db.execute(jobs_q)).scalar() or 0

        # Total candidates
        total_candidates = (
            await self._db.execute(select(func.count()).select_from(Candidate))
        ).scalar() or 0

        # Applications this week
        week_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
        apps_q = (
            select(func.count())
            .select_from(Application)
            .where(Application.created_at >= week_ago)
        )
        if company_id:
            apps_q = apps_q.where(Application.company_id == company_id)
        weekly_apps = (await self._db.execute(apps_q)).scalar() or 0

        # Pending offers
        offers_q = (
            select(func.count())
            .select_from(__import__("app.models.recruitment", fromlist=["Offer"]).Offer)
            .where(__import__("app.models.recruitment", fromlist=["Offer"]).Offer.status == "SENT")
        )
        if company_id:
            offers_q = offers_q.where(
                __import__("app.models.recruitment", fromlist=["Offer"]).Offer.company_id == company_id
            )
        pending_offers = (await self._db.execute(offers_q)).scalar() or 0

        return {
            "active_jobs": int(total_jobs),
            "total_candidates": int(total_candidates),
            "weekly_applications": int(weekly_apps),
            "pending_offers": int(pending_offers),
        }


def get_analytics_service(db: AsyncSession) -> AnalyticsService:
    """Factory function for analytics service (for DI)."""
    return AnalyticsService(db)
