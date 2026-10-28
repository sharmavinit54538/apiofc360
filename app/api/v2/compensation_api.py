"""API v2 router for the AI Compensation recommendation Engine."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.compensation_service import CompensationService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/compensation",
    tags=["AI Compensation Engine v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


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


# ---------------------------------------------------------------------------
# Batch 6: compensation bands and enterprise pay analytics
# ---------------------------------------------------------------------------
from datetime import date as _date
from app.api.v2.enterprise_dependencies import (
    company_id as _tenant_id, ok as _ok, require_admin as _require_admin,
    require_manager as _require_manager, translate as _translate,
)
from app.services.compensation_service import CompensationBandService


class CompensationBandRequest(BaseModel):
    band_code: str
    grade: str
    name: str
    min_paise: int = Field(ge=0)
    mid_paise: int = Field(ge=0)
    max_paise: int = Field(ge=0)
    effective_date: _date
    department: str | None = None
    designation: str | None = None


class BandAssignmentRequest(BaseModel):
    employee_id: uuid.UUID
    annual_salary_paise: int = Field(ge=0)
    effective_date: _date
    change_reason: str | None = None


class MarketBandBenchmarkRequest(BaseModel):
    grade: str
    designation: str
    region: str = "IN"
    min_paise: int = Field(ge=0)
    median_paise: int = Field(ge=0)
    max_paise: int = Field(ge=0)
    source: str
    effective_date: _date


class IncrementBudgetRequest(BaseModel):
    department: str
    fiscal_year: str
    budget_paise: int = Field(ge=0)
    recommendations: dict[uuid.UUID, float]


@router.post("/bands", status_code=201)
async def create_compensation_band(body: CompensationBandRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        band = await CompensationBandService(db).create_band(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(band.id), "grade": band.grade, "min_paise": band.min_paise, "mid_paise": band.mid_paise, "max_paise": band.max_paise})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/bands/{band_id}/assignments", status_code=201)
async def assign_compensation_band(band_id: uuid.UUID, body: BandAssignmentRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        assignment = await CompensationBandService(db).assign_employee_band(
            company_id=_tenant_id(claims), band_id=band_id, **body.model_dump(),
        )
        return _ok({"id": str(assignment.id), "employee_id": str(assignment.employee_id), "is_current": assignment.is_current})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.get("/employees/{employee_id}/compa-ratio")
async def employee_compa_ratio(employee_id: uuid.UUID, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_manager(claims)
    try:
        return _ok(await CompensationBandService(db).compa_ratio(company_id=_tenant_id(claims), employee_id=employee_id))
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/market-benchmarks", status_code=201)
async def create_band_market_benchmark(body: MarketBandBenchmarkRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        benchmark = await CompensationBandService(db).register_market_benchmark(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(benchmark.id), "median_paise": benchmark.median_paise})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.get("/employees/{employee_id}/market-comparison")
async def employee_market_comparison(employee_id: uuid.UUID, region: str = "IN", claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    _require_manager(claims)
    try:
        return _ok(await CompensationBandService(db).market_comparison(company_id=_tenant_id(claims), employee_id=employee_id, region=region))
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/increment-budgets/model")
async def model_increment_budget(body: IncrementBudgetRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        budget = await CompensationBandService(db).model_department_increment(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(budget.id), "modeled_increment_paise": budget.modeled_increment_paise, **budget.scenario_json})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.get("/pay-equity")
async def pay_equity_report(minimum_group_size: int = 2, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    _require_admin(claims)
    try:
        return _ok(await CompensationBandService(db).pay_equity_report(company_id=_tenant_id(claims), minimum_group_size=minimum_group_size))
    except ValueError as exc:
        _translate(exc)
