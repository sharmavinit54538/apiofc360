"""Performance Management calculations and processing service.

Orchestrates review cycles, OKRs tracking, and local LLM performance audit runs
generating increment rates, promotion targets, skill gap analyses, and learning roadmaps.
"""

from __future__ import annotations

import logging
import json
import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.performance import (
    PerformanceReviewCycle,
    EmployeePerformanceGoal,
    PerformanceReview,
)

logger = logging.getLogger(__name__)


class PerformanceService:
    """Enterprise Performance and Talents audit service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def create_review_cycle(
        self,
        name: str,
        start_date: date,
        end_date: date,
    ) -> PerformanceReviewCycle:
        """Initialize a new quarterly/annual performance evaluation cycle."""
        cycle = PerformanceReviewCycle(
            id=uuid.uuid4(),
            name=name,
            start_date=start_date,
            end_date=end_date,
            status="ACTIVE",
        )
        self.db.add(cycle)
        await self.db.commit()
        await self.db.refresh(cycle)
        logger.info("Performance Review Cycle initialized: %s", cycle.name)
        return cycle

    async def create_employee_goal(
        self,
        employee_id: uuid.UUID,
        title: str,
        target_value: str,
        due_date: date,
        description: Optional[str] = None,
    ) -> EmployeePerformanceGoal:
        """Register a new OKR goal target for tracking."""
        goal = EmployeePerformanceGoal(
            id=uuid.uuid4(),
            employee_id=employee_id,
            title=title,
            description=description,
            target_value=target_value,
            current_value="0",
            due_date=due_date,
            status="PENDING",
        )
        self.db.add(goal)
        await self.db.commit()
        await self.db.refresh(goal)
        logger.info("Performance goal registered: %s for employee %s", goal.title, employee_id)
        return goal

    async def evaluate_employee_performance(
        self,
        review_id: uuid.UUID,
        model: Optional[str] = None,
    ) -> PerformanceReview:
        """Call LLM audit engine to evaluate review inputs and generate talent recommendations."""
        stmt = (
            select(PerformanceReview)
            .options(selectinload(PerformanceReview.employee))
            .where(PerformanceReview.id == review_id)
        )
        res = await self.db.execute(stmt)
        review = res.scalar_one_or_none()
        if not review:
            raise ValueError("Performance review record not found.")

        # Query all active goals for the employee
        goals_stmt = select(EmployeePerformanceGoal).where(
            EmployeePerformanceGoal.employee_id == review.employee_id
        )
        goals_res = await self.db.execute(goals_stmt)
        goals = goals_res.scalars().all()

        goals_lines = []
        for g in goals:
            goals_lines.append(
                f"- Title: {g.title}, Target: {g.target_value}, "
                f"Current: {g.current_value}, Status: {g.status}"
            )
        goals_data = "\n".join(goals_lines) or "No OKR goals configured."

        ratings_data = (
            f"Self Rating: {review.self_rating or 'Not rated'}\n"
            f"Manager Rating: {review.reviewer_rating or 'Not rated'}"
        )

        peer_feedback = json.dumps(review.feedback_360 or {}, indent=2)

        try:
            prompt = PromptLibrary.ai_performance_user(goals_data, ratings_data, peer_feedback)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_PERFORMANCE_REVIEW_EVALUATION,
                model=model,
                json_mode=True,
                temperature=0.1
            )
            eval_data = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("AI Performance Review evaluation failed: %s", exc)
            eval_data = {
                "ai_overall_score": 3.00,
                "ai_review_justification": "AI check failed due to client error. Fallback score assigned.",
                "promotion_recommendation": False,
                "salary_increment_percentage": 0.00,
                "skill_gap_analysis": {"identified_gaps": []},
                "learning_recommendations": []
            }

        # Update evaluation fields
        review.ai_overall_score = Decimal(str(eval_data.get("ai_overall_score", 3.00)))
        review.ai_review_justification = eval_data.get("ai_review_justification", "")
        review.promotion_recommendation = bool(eval_data.get("promotion_recommendation", False))
        review.salary_increment_percentage = Decimal(str(eval_data.get("salary_increment_percentage", 0.00)))
        review.skill_gap_analysis = eval_data.get("skill_gap_analysis", {})
        review.learning_recommendations = eval_data.get("learning_recommendations", [])
        
        review.status = "COMPLETED"
        review.updated_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(review)
        logger.info("AI review completed for Employee %s: Score %s", review.employee_id, review.ai_overall_score)
        return review


class PerformanceEnterpriseService:
    """Tenant-scoped 360 reviews, deterministic calibration, and promotions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _cycle(self, cycle_id: uuid.UUID, company_id: uuid.UUID):
        from app.models.performance import PerformanceCycleV2
        cycle = (await self.session.execute(select(PerformanceCycleV2).where(
            PerformanceCycleV2.id == cycle_id, PerformanceCycleV2.company_id == company_id,
        ))).scalar_one_or_none()
        if cycle is None:
            raise LookupError("Performance cycle not found.")
        return cycle

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        from app.models.employee import Employee
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted.is_(False),
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Employee not found in this tenant.")
        return employee

    async def create_cycle(
        self, *, company_id: uuid.UUID, name: str, start_date: date, end_date: date,
        bell_curve_targets: dict[str, float] | None = None,
    ):
        from app.models.performance import PerformanceCycleV2
        if end_date <= start_date:
            raise ValueError("Performance cycle end date must be after its start date.")
        targets = bell_curve_targets or {"5": 10, "4": 20, "3": 40, "2": 20, "1": 10}
        self._validate_targets(targets)
        cycle = PerformanceCycleV2(
            id=uuid.uuid4(), company_id=company_id, name=name.strip(), start_date=start_date,
            end_date=end_date, status="OPEN", bell_curve_targets=targets,
        )
        self.session.add(cycle)
        await self.session.commit()
        return cycle

    @staticmethod
    def _validate_targets(targets: dict[str, float]) -> None:
        if not targets or any(str(key) not in {"1", "2", "3", "4", "5"} for key in targets):
            raise ValueError("Bell-curve targets must use ratings 1 through 5.")
        if any(Decimal(str(value)) < 0 for value in targets.values()):
            raise ValueError("Bell-curve percentages cannot be negative.")
        if sum((Decimal(str(value)) for value in targets.values()), Decimal("0")) != Decimal("100"):
            raise ValueError("Bell-curve target percentages must total 100.")

    async def add_review(
        self, *, company_id: uuid.UUID, cycle_id: uuid.UUID, employee_id: uuid.UUID,
        reviewer_id: uuid.UUID, review_type: str,
    ):
        from app.models.performance import PerformanceReview360
        from app.models.user import User
        cycle = await self._cycle(cycle_id, company_id)
        if cycle.status != "OPEN":
            raise ValueError("Reviews can only be added to an open cycle.")
        employee = await self._employee(employee_id, company_id)
        reviewer = (await self.session.execute(select(User).where(
            User.id == reviewer_id, User.company_id == company_id, User.is_active.is_(True),
        ))).scalar_one_or_none()
        if reviewer is None:
            raise LookupError("Reviewer not found or inactive in this tenant.")
        review_type = review_type.upper()
        if review_type not in {"SELF", "MANAGER", "PEER"}:
            raise ValueError("Review type must be SELF, MANAGER, or PEER.")
        if review_type == "SELF" and employee.user_id != reviewer_id:
            raise ValueError("A self review must be submitted by the employee's own user account.")
        if review_type != "SELF" and employee.user_id == reviewer_id:
            raise ValueError("Manager and peer reviews require a different reviewer.")
        review = PerformanceReview360(
            id=uuid.uuid4(), company_id=company_id, cycle_id=cycle_id,
            employee_id=employee_id, reviewer_id=reviewer_id, review_type=review_type,
        )
        self.session.add(review)
        await self.session.commit()
        return review

    async def submit_review(
        self, review_id: uuid.UUID, *, company_id: uuid.UUID,
        reviewer_id: uuid.UUID, rating: float, comments: str | None = None,
    ):
        from app.models.performance import PerformanceReview360
        score = Decimal(str(rating))
        if score < 0 or score > 5:
            raise ValueError("Review rating must be between 0 and 5.")
        review = (await self.session.execute(select(PerformanceReview360).where(
            PerformanceReview360.id == review_id, PerformanceReview360.company_id == company_id,
        ))).scalar_one_or_none()
        if review is None:
            raise LookupError("Performance review not found.")
        if review.reviewer_id != reviewer_id:
            raise PermissionError("Only the assigned reviewer may submit this review.")
        if review.status == "SUBMITTED":
            raise ValueError("This review has already been submitted.")
        review.rating = score
        review.comments = comments
        review.status = "SUBMITTED"
        review.submitted_at = datetime.utcnow()
        await self.session.commit()
        return review

    @staticmethod
    def _rating_quotas(targets: dict[str, float], count: int) -> dict[int, int]:
        raw = {int(key): Decimal(count) * Decimal(str(targets.get(str(key), 0))) / 100 for key in targets}
        quotas = {rating: int(value) for rating, value in raw.items()}
        remaining = count - sum(quotas.values())
        fractions = sorted(raw, key=lambda rating: (raw[rating] - int(raw[rating]), rating), reverse=True)
        for rating in fractions[:remaining]:
            quotas[rating] += 1
        return quotas

    async def calibrate_cycle(self, cycle_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID):
        from app.models.performance import PerformanceCalibrationRun, PerformanceReview360
        cycle = await self._cycle(cycle_id, company_id)
        if cycle.status not in {"OPEN", "IN_REVIEW"}:
            raise ValueError("This cycle has already been calibrated or closed.")
        reviews = (await self.session.execute(select(PerformanceReview360).where(
            PerformanceReview360.company_id == company_id,
            PerformanceReview360.cycle_id == cycle_id,
            PerformanceReview360.review_type == "MANAGER",
        ))).scalars().all()
        if not reviews or any(review.status != "SUBMITTED" or review.rating is None for review in reviews):
            raise ValueError("All manager reviews must be submitted before calibration.")
        grouped: dict[uuid.UUID, list[PerformanceReview360]] = {}
        for review in reviews:
            grouped.setdefault(review.employee_id, []).append(review)
        raw_scores = {
            employee_id: sum((Decimal(str(review.rating)) for review in items), Decimal("0")) / Decimal(len(items))
            for employee_id, items in grouped.items()
        }
        ranked = sorted(raw_scores, key=lambda employee_id: (raw_scores[employee_id], str(employee_id)), reverse=True)
        quotas = self._rating_quotas(cycle.bell_curve_targets, len(ranked))
        assignments: dict[uuid.UUID, int] = {}
        cursor = 0
        for rating in sorted(quotas, reverse=True):
            for employee_id in ranked[cursor:cursor + quotas[rating]]:
                assignments[employee_id] = rating
            cursor += quotas[rating]
        result_rows = []
        for employee_id, items in grouped.items():
            calibrated = assignments[employee_id]
            for review in items:
                review.calibrated_rating = Decimal(calibrated)
            result_rows.append({
                "employee_id": str(employee_id), "raw_rating": float(raw_scores[employee_id].quantize(Decimal("0.01"))),
                "calibrated_rating": calibrated,
            })
        run = PerformanceCalibrationRun(
            id=uuid.uuid4(), company_id=company_id, cycle_id=cycle_id, status="COMPLETED",
            target_distribution=cycle.bell_curve_targets, started_by=actor_id,
            completed_at=datetime.utcnow(),
            result_json={"employees": result_rows, "actual_distribution": {str(key): value for key, value in quotas.items()}},
        )
        cycle.status = "CALIBRATED"
        self.session.add(run)
        await self.session.commit()
        return run

    async def latest_employee_score(self, *, company_id: uuid.UUID, employee_id: uuid.UUID) -> Decimal | None:
        from app.models.performance import PerformanceCycleV2, PerformanceReview360
        rows = (await self.session.execute(
            select(PerformanceReview360, PerformanceCycleV2.end_date)
            .join(PerformanceCycleV2, PerformanceCycleV2.id == PerformanceReview360.cycle_id)
            .where(
                PerformanceReview360.company_id == company_id,
                PerformanceReview360.employee_id == employee_id,
                PerformanceReview360.review_type == "MANAGER",
                PerformanceReview360.status == "SUBMITTED",
                PerformanceCycleV2.company_id == company_id,
            ).order_by(PerformanceCycleV2.end_date.desc())
        )).all()
        if not rows:
            return None
        latest_end = rows[0][1]
        ratings = [Decimal(str(review.calibrated_rating if review.calibrated_rating is not None else review.rating)) for review, end_date in rows if end_date == latest_end]
        return (sum(ratings, Decimal("0")) / Decimal(len(ratings))).quantize(Decimal("0.01")) if ratings else None

    async def create_promotion_request(
        self, *, company_id: uuid.UUID, cycle_id: uuid.UUID, employee_id: uuid.UUID,
        target_band_id: uuid.UUID, requested_by: uuid.UUID, justification: str,
    ):
        from app.models.compensation import CompensationBand, EmployeeCompensationBand
        from app.models.performance import PerformanceReview360, PromotionApproval
        from app.services.compensation_service import CompensationBandService
        await self._cycle(cycle_id, company_id)
        await self._employee(employee_id, company_id)
        review = (await self.session.execute(select(PerformanceReview360).where(
            PerformanceReview360.company_id == company_id, PerformanceReview360.cycle_id == cycle_id,
            PerformanceReview360.employee_id == employee_id, PerformanceReview360.review_type == "MANAGER",
            PerformanceReview360.calibrated_rating.isnot(None),
        ).order_by(PerformanceReview360.submitted_at.desc()).limit(1))).scalar_one_or_none()
        if review is None:
            raise ValueError("A calibrated manager review is required before promotion recommendation.")
        target_band = (await self.session.execute(select(CompensationBand).where(
            CompensationBand.id == target_band_id, CompensationBand.company_id == company_id,
            CompensationBand.is_active.is_(True),
        ))).scalar_one_or_none()
        if target_band is None:
            raise LookupError("Target compensation band not found.")
        current = (await self.session.execute(select(CompensationBand.grade)
            .join(EmployeeCompensationBand, EmployeeCompensationBand.band_id == CompensationBand.id)
            .where(
                EmployeeCompensationBand.company_id == company_id,
                EmployeeCompensationBand.employee_id == employee_id,
                EmployeeCompensationBand.is_current.is_(True),
            ).limit(1))).scalar_one_or_none()
        if current is None:
            raise ValueError("Employee has no current compensation band.")
        if len(justification.strip()) < 10:
            raise ValueError("Promotion justification is required.")
        recommendation = await CompensationBandService(self.session).recommend_increment(
            company_id=company_id, employee_id=employee_id, calibrated_rating=float(review.calibrated_rating),
        )
        promotion = PromotionApproval(
            id=uuid.uuid4(), company_id=company_id, cycle_id=cycle_id, employee_id=employee_id,
            current_grade=current, target_grade=target_band.grade, target_band_id=target_band.id,
            recommended_increment_percentage=Decimal(str(recommendation["recommended_increment_percentage"])),
            requested_by=requested_by, justification=justification.strip(),
        )
        self.session.add(promotion)
        await self.session.commit()
        return promotion

    async def decide_promotion(
        self, promotion_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_id: uuid.UUID, stage: str, approved: bool,
    ):
        from app.models.performance import PromotionApproval
        promotion = (await self.session.execute(select(PromotionApproval).where(
            PromotionApproval.id == promotion_id, PromotionApproval.company_id == company_id,
        ))).scalar_one_or_none()
        if promotion is None:
            raise LookupError("Promotion approval not found.")
        stage = stage.upper()
        if stage == "MANAGER" and promotion.status == "PENDING_MANAGER":
            promotion.status = "PENDING_HR" if approved else "REJECTED"
            promotion.manager_approved_by = actor_id
        elif stage == "HR" and promotion.status == "PENDING_HR":
            promotion.status = "APPROVED" if approved else "REJECTED"
            promotion.hr_approved_by = actor_id
        else:
            raise ValueError("Promotion decision is out of sequence or already completed.")
        if promotion.status in {"APPROVED", "REJECTED"}:
            promotion.decided_at = datetime.utcnow()
        await self.session.commit()
        return promotion
