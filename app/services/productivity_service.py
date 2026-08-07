"""AI Productivity Tracking and pattern analysis service.

Orchestrates daily logs metric captures and local LLM performance forecasting audits.
"""

from __future__ import annotations

import logging
import json
import uuid
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.productivity import (
    EmployeeProductivityLog,
    ProductivityForecastingRun,
)

logger = logging.getLogger(__name__)


class ProductivityService:
    """Enterprise Employee Productivity tracking service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def log_daily_productivity(
        self,
        employee_id: uuid.UUID,
        focus_score: Decimal,
        deep_work_hours: Decimal,
        idle_hours: Decimal,
        meeting_hours: Decimal,
        tasks_completed_count: int,
        recorded_date: Optional[date] = None,
    ) -> EmployeeProductivityLog:
        """Record daily tracked productivity details."""
        # Verify employee
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalar_one_or_none()
        if not emp:
            raise ValueError("Employee not found.")

        log = EmployeeProductivityLog(
            id=uuid.uuid4(),
            employee_id=employee_id,
            focus_score=focus_score,
            deep_work_hours=deep_work_hours,
            idle_hours=idle_hours,
            meeting_hours=meeting_hours,
            tasks_completed_count=tasks_completed_count,
            recorded_date=recorded_date or date.today(),
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info("Productivity log recorded for employee %s", employee_id)
        return log

    async def forecast_employee_productivity(
        self,
        employee_id: uuid.UUID,
        model: Optional[str] = None,
    ) -> ProductivityForecastingRun:
        """Fetch past productivity logs and run AI evaluation to predict burnout and focus score."""
        # Verify employee
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalar_one_or_none()
        if not emp:
            raise ValueError("Employee not found.")

        # Query past 7 days of logs
        seven_days_ago = date.today() - timedelta(days=7)
        logs_stmt = (
            select(EmployeeProductivityLog)
            .where(
                EmployeeProductivityLog.employee_id == employee_id,
                EmployeeProductivityLog.recorded_date >= seven_days_ago
            )
            .order_by(EmployeeProductivityLog.recorded_date.desc())
        )
        logs_res = await self.db.execute(logs_stmt)
        logs = logs_res.scalars().all()

        lines = []
        for l in logs:
            lines.append(
                f"- Date: {l.recorded_date}, Focus: {l.focus_score}, "
                f"Deep Work: {l.deep_work_hours}h, Idle: {l.idle_hours}h, "
                f"Meetings: {l.meeting_hours}h, Tasks Completed: {l.tasks_completed_count}"
            )
        historical_logs = "\n".join(lines) or "No historical log records for the past 7 days."

        try:
            prompt = PromptLibrary.ai_productivity_user(historical_logs)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_PRODUCTIVITY_FORECASTING,
                model=model,
                json_mode=True,
                temperature=0.2
            )
            forecast = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("AI Productivity Forecasting failed: %s", exc)
            forecast = {
                "predicted_focus_score": 75.00,
                "predicted_burnout_risk": "MEDIUM",
                "ai_recommendations": "Default auto-monitoring active. Save deep-work buffers."
            }

        # Register forecasting report
        run = ProductivityForecastingRun(
            id=uuid.uuid4(),
            employee_id=employee_id,
            predicted_focus_score=Decimal(str(forecast.get("predicted_focus_score", 75.00))),
            predicted_burnout_risk=forecast.get("predicted_burnout_risk", "MEDIUM").upper(),
            ai_recommendations=forecast.get("ai_recommendations", ""),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Productivity forecast run compiled: %s", run.id)
        return run
