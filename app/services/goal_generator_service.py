"""AI Goal Generator services.

Orchestrates automatic setups of OKRs, KPIs, department goals,
and dynamic performance calibrations.
"""

from __future__ import annotations

import logging
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.generated_goal import GeneratedGoal

logger = logging.getLogger(__name__)


class GoalGeneratorService:
    """Enterprise AI Goal Architecture and Adjustment Service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def generate_and_save_goals(
        self,
        company_id: uuid.UUID,
        employee_id: Optional[uuid.UUID],
        goal_type: str,  # OKR, KPI, TEAM_GOAL, DEPARTMENT_GOAL, QUARTERLY_GOAL, WEEKLY_GOAL, DAILY_TASK
        scope: str,  # INDIVIDUAL, TEAM, DEPARTMENT, COMPANY
        department: str,
        details: str,
        model: Optional[str] = None,
    ) -> list[GeneratedGoal]:
        """Automatically compile and register a list of goals via LLM."""
        if employee_id:
            emp_stmt = select(Employee).where(Employee.id == employee_id)
            emp_res = await self.db.execute(emp_stmt)
            emp = emp_res.scalar_one_or_none()
            if not emp:
                raise ValueError("Employee not found.")

        try:
            prompt = PromptLibrary.ai_goal_generator_user(
                goal_type=goal_type.upper(),
                scope=scope.upper(),
                department=department,
                details=details
            )
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_GOAL_GENERATOR,
                model=model,
                json_mode=True,
                temperature=0.3
            )
            data = ResponseParser.extract_json_object(res_text)
            goals_list = data.get("goals", [])
        except Exception as exc:
            logger.error("AI Goal generation failed: %s", exc)
            goals_list = [
                {
                    "title": f"Complete {goal_type.upper()} targets",
                    "description": f"Focus on core KPIs for department {department}.",
                    "target_metric": "100% completion",
                    "due_in_days": 30
                }
            ]

        saved_goals = []
        for g in goals_list:
            due_days = g.get("due_in_days", 30)
            due_date = date.today() + timedelta(days=due_days)

            goal = GeneratedGoal(
                id=uuid.uuid4(),
                company_id=company_id,
                employee_id=employee_id,
                goal_type=goal_type.upper(),
                scope=scope.upper(),
                title=g.get("title", ""),
                description=g.get("description", ""),
                target_metric=g.get("target_metric", "100%"),
                current_value="0",
                status="ACTIVE",
                due_date=due_date
            )
            self.db.add(goal)
            saved_goals.append(goal)

        await self.db.commit()
        for g in saved_goals:
            await self.db.refresh(g)
        logger.info("Generated %s goals for employee %s", len(saved_goals), employee_id)
        return saved_goals

    async def adjust_goals_on_performance(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        performance_summary: str,
        model: Optional[str] = None,
    ) -> list[GeneratedGoal]:
        """Review existing goals list and apply re-calibrations based on performance trends."""
        # Query active goals
        stmt = select(GeneratedGoal).where(
            GeneratedGoal.employee_id == employee_id,
            GeneratedGoal.status.in_(["ACTIVE", "ADJUSTED"])
        )
        res = await self.db.execute(stmt)
        active_goals = res.scalars().all()

        if not active_goals:
            logger.info("No active generated goals found for employee %s to calibrate.", employee_id)
            return []

        # Summarize goals details for LLM
        lines = []
        for g in active_goals:
            lines.append(
                f"- ID: {g.id}, Title: {g.title}, Target: {g.target_metric}, Current: {g.current_value}"
            )
        goals_text = "\n".join(lines)

        try:
            prompt = PromptLibrary.ai_goal_adjuster_user(goals_text, performance_summary)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_GOAL_ADJUSTER,
                model=model,
                json_mode=True,
                temperature=0.2
            )
            adjustments_data = ResponseParser.extract_json_object(res_text)
            adjustments = adjustments_data.get("adjustments", [])
        except Exception as exc:
            logger.error("AI Goal adjustment failed: %s", exc)
            adjustments = []

        # Apply adjustments
        adjusted_goals = []
        for adj in adjustments:
            goal_id_str = adj.get("goal_id")
            if not goal_id_str:
                continue
            try:
                goal_uuid = uuid.UUID(goal_id_str)
            except ValueError:
                continue

            # Match active goals in-memory to save query lookups
            matched_goal = next((g for g in active_goals if g.id == goal_uuid), None)
            if matched_goal:
                if not matched_goal.original_target:
                    matched_goal.original_target = matched_goal.target_metric

                matched_goal.target_metric = adj.get("target_metric", matched_goal.target_metric)
                matched_goal.status = adj.get("status", "ADJUSTED").upper()
                matched_goal.adjustment_reason = adj.get("adjustment_reason")
                adjusted_goals.append(matched_goal)

        await self.db.commit()
        for g in adjusted_goals:
            await self.db.refresh(g)
            logger.info("Calibrated goal %s targets: %s", g.id, g.target_metric)
        return adjusted_goals
