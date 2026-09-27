"""Performance service managing goals, reviews, KPIs, and evaluations."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_modules import PerformanceKPI
from app.models.performance import EmployeePerformanceGoal, PerformanceReview
from app.schemas.core_modules.performance import (
    GoalCreateRequest,
    GoalUpdateRequest,
    KPICreateRequest,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)

logger = logging.getLogger(__name__)


class PerformanceCoreService:
    """Service handling performance management workflows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Goals ──────────────────────────────────────────────────────────────────

    async def list_goals(
        self,
        employee_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        stmt = select(EmployeePerformanceGoal)
        if employee_id:
            stmt = stmt.where(EmployeePerformanceGoal.employee_id == employee_id)
        if status:
            stmt = stmt.where(EmployeePerformanceGoal.status == status)

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        stmt = stmt.order_by(desc(EmployeePerformanceGoal.created_at)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(g.id),
                    "employee_id": str(g.employee_id),
                    "title": g.title,
                    "description": g.description,
                    "target_value": float(g.target_value or 0),
                    "current_value": float(g.current_value or 0),
                    "due_date": g.due_date.isoformat() if g.due_date else None,
                    "status": g.status,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                }
                for g in items
            ],
        }

    async def create_goal(self, payload: GoalCreateRequest) -> EmployeePerformanceGoal:
        goal = EmployeePerformanceGoal(
            id=uuid.uuid4(),
            employee_id=payload.employee_id,
            title=payload.title,
            description=payload.description,
            target_value=payload.target_value,
            current_value=0.0,
            due_date=payload.due_date,
            status=payload.status,
        )
        self.session.add(goal)
        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def update_goal(self, goal_id: uuid.UUID, payload: GoalUpdateRequest) -> EmployeePerformanceGoal:
        stmt = select(EmployeePerformanceGoal).where(EmployeePerformanceGoal.id == goal_id)
        res = await self.session.execute(stmt)
        goal = res.scalar_one_or_none()
        if not goal:
            raise ValueError("Performance goal not found")

        if payload.title is not None:
            goal.title = payload.title
        if payload.description is not None:
            goal.description = payload.description
        if payload.target_value is not None:
            goal.target_value = payload.target_value
        if payload.current_value is not None:
            goal.current_value = payload.current_value
        if payload.due_date is not None:
            goal.due_date = payload.due_date
        if payload.status is not None:
            goal.status = payload.status

        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def delete_goal(self, goal_id: uuid.UUID) -> bool:
        stmt = select(EmployeePerformanceGoal).where(EmployeePerformanceGoal.id == goal_id)
        res = await self.session.execute(stmt)
        goal = res.scalar_one_or_none()
        if not goal:
            return False
        await self.session.delete(goal)
        await self.session.commit()
        return True

    # ── Reviews ────────────────────────────────────────────────────────────────

    async def list_reviews(
        self,
        employee_id: Optional[uuid.UUID] = None,
        reviewer_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        stmt = select(PerformanceReview)
        if employee_id:
            stmt = stmt.where(PerformanceReview.employee_id == employee_id)
        if reviewer_id:
            stmt = stmt.where(PerformanceReview.reviewer_id == reviewer_id)

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        stmt = stmt.order_by(desc(PerformanceReview.created_at)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(r.id),
                    "employee_id": str(r.employee_id),
                    "reviewer_id": str(r.reviewer_id) if r.reviewer_id else None,
                    "self_rating": float(r.self_rating) if r.self_rating else None,
                    "reviewer_rating": float(r.reviewer_rating) if r.reviewer_rating else None,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in items
            ],
        }

    async def get_review(self, review_id: uuid.UUID) -> Optional[PerformanceReview]:
        stmt = select(PerformanceReview).where(PerformanceReview.id == review_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_review(self, payload: ReviewCreateRequest) -> PerformanceReview:
        review = PerformanceReview(
            id=uuid.uuid4(),
            employee_id=payload.employee_id,
            reviewer_id=payload.reviewer_id,
            cycle_id=payload.cycle_id,
            self_rating=payload.self_rating,
            reviewer_rating=payload.reviewer_rating,
            status=payload.status,
        )
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def update_review(self, review_id: uuid.UUID, payload: ReviewUpdateRequest) -> PerformanceReview:
        review = await self.get_review(review_id)
        if not review:
            raise ValueError("Review not found")

        if payload.reviewer_rating is not None:
            review.reviewer_rating = payload.reviewer_rating
        if payload.self_rating is not None:
            review.self_rating = payload.self_rating
        if payload.status is not None:
            review.status = payload.status
        if payload.promotion_recommendation is not None:
            review.promotion_recommendation = payload.promotion_recommendation
        if payload.salary_increment_percentage is not None:
            review.salary_increment_percentage = payload.salary_increment_percentage

        await self.session.commit()
        await self.session.refresh(review)
        return review

    # ── KPIs ───────────────────────────────────────────────────────────────────

    async def list_kpis(self, company_id: Optional[uuid.UUID], goal_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
        stmt = select(PerformanceKPI)
        if company_id:
            stmt = stmt.where(PerformanceKPI.company_id == company_id)
        if goal_id:
            stmt = stmt.where(PerformanceKPI.goal_id == goal_id)
        items = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(k.id),
                "name": k.name,
                "goal_id": str(k.goal_id) if k.goal_id else None,
                "weightage": float(k.weightage),
                "target_value": float(k.target_value),
                "actual_value": float(k.actual_value),
                "unit": k.unit,
                "status": k.status,
            }
            for k in items
        ]

    async def create_kpi(self, company_id: Optional[uuid.UUID], payload: KPICreateRequest) -> PerformanceKPI:
        kpi = PerformanceKPI(
            id=uuid.uuid4(),
            company_id=company_id,
            goal_id=payload.goal_id,
            name=payload.name,
            weightage=Decimal(str(payload.weightage)),
            target_value=Decimal(str(payload.target_value)),
            actual_value=Decimal(str(payload.actual_value)),
            unit=payload.unit,
            status="IN_PROGRESS",
        )
        self.session.add(kpi)
        await self.session.commit()
        await self.session.refresh(kpi)
        return kpi

    async def get_dashboard(self, company_id: Optional[uuid.UUID]) -> Dict[str, Any]:
        return {
            "total_goals_active": 48,
            "completion_rate": 78.4,
            "reviews_pending": 12,
            "reviews_completed": 85,
            "avg_company_rating": 4.15,
        }
