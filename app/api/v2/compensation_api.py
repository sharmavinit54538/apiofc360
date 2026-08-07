"""API v2 router for the AI Compensation recommendation Engine."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.compensation_service import CompensationService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compensation", tags=["AI Compensation Engine v2"])


# Requests
class RegisterBenchmarkRequest(BaseModel):
    designation: str
    experience_years: int = Field(..., ge=0)
    market_min_salary: Decimal = Field(..., ge=0.0)
    market_median_salary: Decimal = Field(..., ge=0.0)
    market_max_salary: Decimal = Field(..., ge=0.0)
    region: str = "Global"

class CompileRecommendationRequest(BaseModel):
    model: Optional[str] = None


@router.post(
    "/benchmarks",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Register market salary benchmarks",
)
async def register_benchmark(
    body: RegisterBenchmarkRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Upserts baseline benchmarks salaries for various titles and seniorities levels."""
    service = CompensationService(db)
    benchmark = await service.register_market_benchmark(
        designation=body.designation,
        experience_years=body.experience_years,
        market_min_salary=body.market_min_salary,
        market_median_salary=body.market_median_salary,
        market_max_salary=body.market_max_salary,
        region=body.region
    )

    return APIResponse[dict](
        success=True,
        message="Market compensation benchmark registered successfully.",
        data={
            "benchmark_id": str(benchmark.id),
            "designation": benchmark.designation,
            "market_median_salary": float(benchmark.market_median_salary),
        },
        errors=None
    )


@router.post(
    "/recommendations/{employee_id}",
    response_model=APIResponse[dict],
    summary="Compile AI compensation recommendations for staff members",
)
async def compile_recommendation(
    employee_id: uuid.UUID,
    body: CompileRecommendationRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Performs internal department colleague audits and calls local LLM to draft bonuses, options and promotions."""
    service = CompensationService(db)
    try:
        rec = await service.compile_compensation_recommendation(employee_id, model=body.model)
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Compensation package recommendation compiled successfully.",
        data={
            "recommendation_id": str(rec.id),
            "recommended_salary": float(rec.recommended_salary),
            "recommended_bonus": float(rec.recommended_bonus),
            "recommended_stock_options": rec.recommended_stock_options,
            "recommend_promotion": rec.recommend_promotion,
            "recommended_title": rec.recommended_title,
            "equity_status": rec.equity_status,
            "justification": rec.justification,
        },
        errors=None
    )
