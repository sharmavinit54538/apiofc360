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
