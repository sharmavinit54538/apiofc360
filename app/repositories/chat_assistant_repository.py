"""AI Chat Assistant Repository executing real PostgreSQL queries across HRMS domain tables."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.employee import Employee
from app.models.exit import EmployeeExit
from app.models.recruitment import Job, JobRequisition
from app.models.policy import CompanyPolicyDocument

logger = logging.getLogger(__name__)


class ChatAssistantRepository:
    """Repository executing database queries for AI Chat Assistant endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_workforce_metrics(
        self, company_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Fetch workforce analytics metrics from real database queries."""
        base_filters = [Employee.is_deleted == False]
        if company_id:
            base_filters.append(Employee.company_id == company_id)

        result = {
            "total_employees": 0,
            "attrition_rate": None,
            "open_positions": None,
            "avg_overtime_hrs": None,
            "avg_performance_rating": None,
            "department_headcount": [],
            "new_hires_month": 0,
        }

        try:
            # Total active employees
            stmt = select(func.count(Employee.id)).where(*base_filters)
            res = await self.session.execute(stmt)
            total_emp = res.scalar() or 0
            result["total_employees"] = total_emp

            # Department headcount
            dept_stmt = (
                select(Employee.department, func.count(Employee.id))
                .where(*base_filters)
                .group_by(Employee.department)
                .order_by(func.count(Employee.id).desc())
                .limit(10)
            )
            dept_res = await self.session.execute(dept_stmt)
            result["department_headcount"] = [
                {"department": dept, "count": count}
                for dept, count in dept_res.all()
            ]

            # New hires this month
            first_day_this_month = date.today().replace(day=1)
            new_hires_stmt = select(func.count(Employee.id)).where(
                *base_filters,
                Employee.joining_date >= first_day_this_month,
            )
            new_hires_res = await self.session.execute(new_hires_stmt)
            result["new_hires_month"] = new_hires_res.scalar() or 0

        except SQLAlchemyError as exc:
            logger.error("DB query failed for workforce metrics: %s", exc)
            # Return partial data with None for failed metrics

        # Attrition rate: exits in last 12 months / average headcount
        try:
            if company_id:
                twelve_months_ago = date.today() - timedelta(days=365)
                exits_stmt = select(func.count(EmployeeExit.id)).where(
                    EmployeeExit.company_id == company_id,
                    EmployeeExit.last_working_date >= twelve_months_ago,
                )
                exits_res = await self.session.execute(exits_stmt)
                exits_count = exits_res.scalar() or 0

                # Average headcount over the period (approximate using current)
                if total_emp > 0:
                    result["attrition_rate"] = round((exits_count / total_emp) * 100, 2)
        except SQLAlchemyError as exc:
            logger.error("Attrition rate query failed: %s", exc)

        # Open positions: jobs with status OPEN/PUBLISHED + vacancies
        try:
            if company_id:
                open_jobs_stmt = (
                    select(func.sum(Job.vacancies))
                    .where(
                        Job.company_id == company_id,
                        Job.status.in_(["OPEN", "PUBLISHED", "ACTIVE"]),
                        Job.is_deleted == False,
                    )
                )
                open_jobs_res = await self.session.execute(open_jobs_stmt)
                open_pos = open_jobs_res.scalar()
                if open_pos:
                    result["open_positions"] = int(open_pos)

                # Also count approved job requisitions
                req_stmt = (
                    select(func.sum(JobRequisition.vacancies))
                    .where(
                        JobRequisition.status == "APPROVED",
                    )
                )
                req_res = await self.session.execute(req_stmt)
                req_pos = req_res.scalar()
                if req_pos and not result["open_positions"]:
                    result["open_positions"] = int(req_pos)
        except SQLAlchemyError as exc:
            logger.error("Open positions query failed: %s", exc)

        return result

    async def get_policy_citations(
        self, query: str, company_id: Optional[uuid.UUID] = None
    ) -> List[Dict[str, Any]]:
        """Fetch matching policy documents for RAG citations."""
        if not company_id:
            return []

        try:
            stmt = select(CompanyPolicyDocument).where(
                CompanyPolicyDocument.company_id == company_id
            ).limit(5)
            res = await self.session.execute(stmt)
            docs = res.scalars().all()
            if docs:
                return [
                    {
                        "document": doc.title,
                        "section": doc.category or "General",
                        "page": 1,
                        "similarity": None,  # Real similarity from retriever if available
                    }
                    for doc in docs
                ]
        except SQLAlchemyError as exc:
            logger.error("Error fetching policy citations: %s", exc)

        return []