"""Analytics API v2 — Recruitment analytics dashboard endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.analytics_service import get_analytics_service
from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.auth import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/analytics",
    tags=["Recruitment Analytics v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


@router.get(
    "/dashboard",
    response_model=APIResponse[dict],
    summary="Get recruitment dashboard summary",
)
async def get_dashboard_summary(
    company_id: str | None = Query(None, description="Filter by company UUID"),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get high-level recruitment dashboard metrics."""
    svc = get_analytics_service(db)
    data = await svc.get_dashboard_summary(company_id=company_id)
    return APIResponse[dict](success=True, message="Dashboard summary retrieved.", data=data, errors=None)


@router.get(
    "/hiring-funnel",
    response_model=APIResponse[dict],
    summary="Get hiring funnel with stage-by-stage conversion",
)
async def get_hiring_funnel(
    company_id: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return hiring funnel: Applied → Shortlisted → Interviewed → Offered → Hired."""
    svc = get_analytics_service(db)
    data = await svc.get_hiring_funnel(company_id=company_id, date_from=date_from, date_to=date_to)
    return APIResponse[dict](success=True, message="Hiring funnel retrieved.", data=data, errors=None)


@router.get(
    "/offer-acceptance-rate",
    response_model=APIResponse[dict],
    summary="Get offer acceptance rate",
)
async def get_offer_acceptance_rate(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365, description="Period in days"),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return offer acceptance/decline rates over a period."""
    svc = get_analytics_service(db)
    data = await svc.get_offer_acceptance_rate(company_id=company_id, days=days)
    return APIResponse[dict](success=True, message="Offer acceptance rate retrieved.", data=data, errors=None)


@router.get(
    "/time-to-hire",
    response_model=APIResponse[dict],
    summary="Get average time-to-hire metrics",
)
async def get_time_to_hire(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return average, min, max, and median time from application to offer."""
    svc = get_analytics_service(db)
    data = await svc.get_time_to_hire(company_id=company_id, days=days)
    return APIResponse[dict](success=True, message="Time-to-hire metrics retrieved.", data=data, errors=None)


@router.get(
    "/source-performance",
    response_model=APIResponse[dict],
    summary="Analyze sourcing channel performance",
)
async def get_source_performance(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return per-source hire rate and shortlist rate."""
    svc = get_analytics_service(db)
    data = await svc.get_source_performance(company_id=company_id, days=days)
    return APIResponse[dict](
        success=True,
        message="Source performance retrieved.",
        data={"sources": data, "period_days": days},
        errors=None,
    )


@router.get(
    "/recruiter-performance",
    response_model=APIResponse[dict],
    summary="Get recruiter performance metrics",
)
async def get_recruiter_performance(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return per-recruiter job creation and pipeline metrics."""
    svc = get_analytics_service(db)
    data = await svc.get_recruiter_performance(company_id=company_id, days=days)
    return APIResponse[dict](
        success=True,
        message="Recruiter performance retrieved.",
        data={"recruiters": data, "period_days": days},
        errors=None,
    )


@router.get(
    "/department",
    response_model=APIResponse[dict],
    summary="Get department-level hiring analytics",
)
async def get_department_analytics(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return hiring fill rate and applicant volume per department."""
    svc = get_analytics_service(db)
    data = await svc.get_department_analytics(company_id=company_id, days=days)
    return APIResponse[dict](
        success=True,
        message="Department analytics retrieved.",
        data={"departments": data, "period_days": days},
        errors=None,
    )


@router.get(
    "/interview-success",
    response_model=APIResponse[dict],
    summary="Get interview completion and pass rates",
)
async def get_interview_success_rate(
    company_id: str | None = Query(None),
    days: int = Query(90, ge=7, le=365),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Return interview completion rate and pass rate."""
    svc = get_analytics_service(db)
    data = await svc.get_interview_success_rate(company_id=company_id, days=days)
    return APIResponse[dict](success=True, message="Interview success rate retrieved.", data=data, errors=None)


def _tenant_id(claims: dict) -> uuid.UUID:
    value = claims.get("company_id") if claims else None
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required.")
    return uuid.UUID(str(value))


@router.get("/culture", response_model=APIResponse[dict], summary="Department culture and burnout analytics")
async def get_culture_analytics(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    from app.services.hr_analytics_service import HRAnalyticsService
    data = await HRAnalyticsService(db).get_culture_analytics(_tenant_id(claims))
    return APIResponse(success=True, message="Culture analytics retrieved.", data=data, errors=None)


@router.get("/diversity", response_model=APIResponse[dict], summary="Workforce diversity and hiring-parity analytics")
async def get_diversity_analytics(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    from app.services.hr_analytics_service import HRAnalyticsService
    data = await HRAnalyticsService(db).get_diversity_analytics(_tenant_id(claims))
    return APIResponse(success=True, message="Diversity analytics retrieved.", data=data, errors=None)


@router.get("/attrition-risk", response_model=APIResponse[dict], summary="Explainable employee flight-risk analytics")
async def get_attrition_risk_analytics(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    as_of_date: date | None = Query(None),
    persist: bool = Query(False, description="Persist assessment snapshots after computing the response"),
    limit: int = Query(100, ge=1, le=500),
):
    from app.services.hr_analytics_service import HRAnalyticsService
    data = await HRAnalyticsService(db).get_attrition_risk_analytics(
        _tenant_id(claims), as_of_date=as_of_date, persist=persist, limit=limit,
    )
    return APIResponse(success=True, message="Attrition-risk analytics retrieved.", data=data, errors=None)
