"""API v2 router for the AI Goal Generator Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.goal_generator_service import GoalGeneratorService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/goals", tags=["AI Goal Generator v2"])


# Requests
class GenerateGoalsRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: Optional[uuid.UUID] = None
    goal_type: str = Field(..., description="OKR | KPI | TEAM_GOAL | DEPARTMENT_GOAL | QUARTERLY_GOAL | WEEKLY_GOAL | DAILY_TASK")
    scope: str = Field("INDIVIDUAL", description="INDIVIDUAL | TEAM | DEPARTMENT | COMPANY")
    department: str
    details: str
    model: Optional[str] = None

class AdjustGoalsRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    performance_summary: str
    model: Optional[str] = None


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Automatically generate OKRs, KPIs, or tasks goals via LLM",
)
async def generate_goals(
    body: GenerateGoalsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generates structured goals containing titles, descriptions, and targets mapped to specific timelines."""
    service = GoalGeneratorService(db)
    try:
        goals = await service.generate_and_save_goals(
            company_id=body.company_id,
            employee_id=body.employee_id,
            goal_type=body.goal_type,
            scope=body.scope,
            department=body.department,
            details=body.details,
            model=body.model
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Goals generated and saved successfully.",
        data={
            "goals_count": len(goals),
            "generated_goals": [
                {
                    "goal_id": str(g.id),
                    "title": g.title,
                    "target_metric": g.target_metric,
                    "due_date": str(g.due_date),
                }
                for g in goals
            ]
        },
        errors=None
    )


@router.post(
    "/adjust",
    response_model=APIResponse[dict],
    summary="Trigger dynamic AI goal re-calibrations",
)
async def adjust_goals(
    body: AdjustGoalsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Evaluates active goals against recent metrics to update target metrics and record reasons."""
    service = GoalGeneratorService(db)
    goals = await service.adjust_goals_on_performance(
        company_id=body.company_id,
        employee_id=body.employee_id,
        performance_summary=body.performance_summary,
        model=body.model
    )

    return APIResponse[dict](
        success=True,
        message="Dynamic goal calibrations checked and updated.",
        data={
            "adjusted_count": len(goals),
            "adjusted_goals": [
                {
                    "goal_id": str(g.id),
                    "title": g.title,
                    "new_target": g.target_metric,
                    "original_target": g.original_target,
                    "reason": g.adjustment_reason,
                }
                for g in goals
            ]
        },
        errors=None
    )
