"""API v2 router for the AI Productivity Tracking Engine."""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.productivity_service import ProductivityService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/productivity", tags=["AI Productivity Tracking v2"])


# Requests
class LogProductivityRequest(BaseModel):
    employee_id: uuid.UUID
    focus_score: Decimal = Field(..., ge=0.0, le=100.0)
    deep_work_hours: Decimal = Field(..., ge=0.0, le=24.0)
    idle_hours: Decimal = Field(..., ge=0.0, le=24.0)
    meeting_hours: Decimal = Field(..., ge=0.0, le=24.0)
    tasks_completed_count: int = Field(..., ge=0)
    recorded_date: Optional[date] = None

class ForecastRequest(BaseModel):
    model: Optional[str] = None


@router.post(
    "/logs",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Record daily tracked employee productivity metrics",
)
async def log_productivity(
    body: LogProductivityRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Saves daily focus scores, deep work hours, meetings and idle patterns logs."""
    service = ProductivityService(db)
    try:
        log = await service.log_daily_productivity(
            employee_id=body.employee_id,
            focus_score=body.focus_score,
            deep_work_hours=body.deep_work_hours,
            idle_hours=body.idle_hours,
            meeting_hours=body.meeting_hours,
            tasks_completed_count=body.tasks_completed_count,
            recorded_date=body.recorded_date
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Daily productivity log recorded.",
        data={
            "log_id": str(log.id),
            "recorded_date": str(log.recorded_date),
            "focus_score": float(log.focus_score),
        },
        errors=None
    )


@router.post(
    "/forecast/{employee_id}",
    response_model=APIResponse[dict],
    summary="Compile AI workforce productivity predictions and recommendations",
)
async def compile_forecast(
    employee_id: uuid.UUID,
    body: ForecastRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Queries logs history and runs local LLM to forecast burnout limits and suggest improvements."""
    service = ProductivityService(db)
    try:
        run = await service.forecast_employee_productivity(employee_id, model=body.model)
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Productivity forecast run compiled successfully.",
        data={
            "forecast_id": str(run.id),
            "predicted_focus_score": float(run.predicted_focus_score),
            "predicted_burnout_risk": run.predicted_burnout_risk,
            "ai_recommendations": run.ai_recommendations,
            "forecasted_at": str(run.forecasted_at),
        },
        errors=None
    )
