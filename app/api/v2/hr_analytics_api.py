"""API v2 router for the Enterprise HR Analytics and Predictive Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.hr_analytics_service import HRAnalyticsService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/hr-analytics",
    tags=["HR Analytics Engine v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


# Schemas
class ForecastRequest(BaseModel):
    forecast_type: str = Field(..., description="HEADCOUNT | PAYROLL_EXPENSE | RECRUITMENT_NEEDS")
    months_ahead: int = Field(3, ge=1, le=12)
    model: Optional[str] = None

class AttritionRequest(BaseModel):
    model: Optional[str] = None


@router.get(
    "/dashboard",
    response_model=APIResponse[dict],
    summary="Get unified executive HR dashboard metrics",
)
async def get_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieves cached demographics, diversity ratios, salary parity, forecasts, and attrition alerts."""
    company_id_raw = claims.get("company_id") if claims else None
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims."
        )
    company_id = uuid.UUID(str(company_id_raw))
    service = HRAnalyticsService(db)
    summary = await service.get_executive_dashboard_summary(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="HR Analytics dashboard details fetched successfully.",
        data=summary,
        errors=None
    )


@router.post(
    "/snapshots",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Trigger new manual analytics snapshot computation",
)
async def compute_snapshot(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Queries raw tables to compute real-time salary, diversity, headcount and leave metrics."""
    company_id_raw = claims.get("company_id") if claims else None
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims."
        )
    company_id = uuid.UUID(str(company_id_raw))
    service = HRAnalyticsService(db)
    snapshot = await service.compute_analytics_snapshot(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="New analytics snapshot generated successfully.",
        data={
            "snapshot_id": str(snapshot.id),
            "date": str(snapshot.snapshot_date),
            "headcount": snapshot.total_headcount,
            "attrition_rate": float(snapshot.overall_attrition_rate),
        },
        errors=None
    )


@router.post(
    "/attrition-prediction/{employee_id}",
    response_model=APIResponse[dict],
    summary="Evaluate attrition risk score for an employee",
)
async def predict_attrition(
    employee_id: uuid.UUID,
    body: AttritionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Evaluates pay parity, overtime checkins, and leaves using AI classification to log resignation risk."""
    company_id_raw = claims.get("company_id") if claims else None
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims."
        )
    company_id = uuid.UUID(str(company_id_raw))
    service = HRAnalyticsService(db)
    try:
        prediction = await service.predict_employee_attrition(employee_id, company_id=company_id, model=body.model)
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Employee attrition risk score evaluated.",
        data={
            "prediction_id": str(prediction.id),
            "employee_id": str(prediction.employee_id),
            "risk_score": float(prediction.risk_score),
            "risk_level": prediction.risk_level,
            "risk_factors": prediction.top_risk_factors,
            "retention_recommendations": prediction.retention_recommendations,
        },
        errors=None
    )


@router.post(
    "/forecast",
    response_model=APIResponse[dict],
    summary="Run AI predictive workforce forecasts",
)
async def run_forecast(
    body: ForecastRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Extrapolates demographic growth or payroll budget expenditures with confidence ranges."""
    company_id_raw = claims.get("company_id") if claims else None
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims."
        )
    company_id = uuid.UUID(str(company_id_raw))
    service = HRAnalyticsService(db)
    try:
        run = await service.run_ai_forecast(
            forecast_type=body.forecast_type,
            company_id=company_id,
            months_ahead=body.months_ahead,
            model=body.model
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="AI Forecasting model run completed.",
        data={
            "forecast_id": str(run.id),
            "type": run.forecast_type,
            "target_date": str(run.forecast_target_date),
            "predicted_value": float(run.predicted_value),
            "confidence_bounds": [float(run.lower_confidence_bound), float(run.upper_confidence_bound)],
            "parameters": run.model_parameters,
        },
        errors=None
    )


@router.get(
    "/leaves/analytics",
    response_model=APIResponse[dict],
    summary="Get unified leave assistant analytics and conflict metrics",
)
async def get_leave_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieves leave availability ratios, overlap conflicts, and weekly forecasts."""
    company_id_raw = claims.get("company_id")
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims."
        )
    
    service = HRAnalyticsService(db)
    summary = await service.get_leave_analytics(uuid.UUID(str(company_id_raw)))
    return APIResponse[dict](
        success=True,
        message="Leave assistant analytics details fetched successfully.",
        data=summary,
        errors=None
    )

