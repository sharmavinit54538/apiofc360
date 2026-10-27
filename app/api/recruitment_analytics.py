"""Recruitment Analytics and Notifications API routes."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr, require_admin_or_hr_or_manager
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    RecruitmentAnalyticsResponse,
    RecruitmentNotificationResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/recruitment", tags=["Recruitment Analytics & Alerts"])


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentAnalyticsResponse],
    summary="Get recruitment funnel and pipeline analytics",
)
@router.get(
    "/recruitment-analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentAnalyticsResponse],
    summary="Get recruitment metrics and pipeline analytics",
)
async def get_analytics(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    start_date: Annotated[date | None, Query(description="Filter from date (YYYY-MM-DD)")] = None,
    end_date: Annotated[date | None, Query(description="Filter to date (YYYY-MM-DD)")] = None,
    department: Annotated[str | None, Query(description="Filter by department")] = None,
    job_id: Annotated[uuid.UUID | None, Query(description="Filter by job ID")] = None,
    company_id: Annotated[uuid.UUID | None, Query(description="Filter by company ID (Super Admin only)")] = None,
) -> APIResponse[RecruitmentAnalyticsResponse]:
    """Retrieve comprehensive recruitment metrics, pipeline breakdown, conversion rates, and time-to-hire.

    Protected by RBAC: Admin and HR roles only.
    """
    user_company_id = claims.get("company_id") if isinstance(claims, dict) else None
    role = str(claims.get("role") or "").lower() if isinstance(claims, dict) else ""

    # Multi-tenancy enforcement:
    # Company HR/Admins are scoped strictly to their company_id from claims.
    # Super Admins can query globally or filter by target company_id via query parameter.
    effective_company_id: uuid.UUID | None = None
    if user_company_id:
        effective_company_id = uuid.UUID(str(user_company_id))
    elif role == "super_admin" and company_id:
        effective_company_id = company_id

    res = await service.get_recruitment_analytics(
        company_id=effective_company_id,
        start_date=start_date,
        end_date=end_date,
        department=department,
        job_id=job_id,
    )
    return APIResponse[RecruitmentAnalyticsResponse](
        success=True,
        message="Analytics retrieved successfully.",
        data=res,
        errors=None,
    )



@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get recruitment stats",
)
@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get recruitment dashboard",
)
@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get recruitment summary",
)
async def get_recruitment_dashboard_stats(
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[dict]:
    """Retrieve recruitment metrics counts. Admin, HR, and Manager."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    res = await service.get_dashboard_stats(company_id=company_id)
    if hasattr(res, "model_dump"):
        res = res.model_dump()
    elif hasattr(res, "dict"):
        res = res.dict()
    return APIResponse[dict](
        success=True,
        message="Stats retrieved successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "/notifications",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[RecruitmentNotificationResponse]],
    summary="List recruiting notifications",
)
async def list_notifications(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[list[RecruitmentNotificationResponse]]:
    """List recruitment notifications for logged in user. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.list_notifications(user_id)
    return APIResponse[list[RecruitmentNotificationResponse]](
        success=True,
        message="Notifications retrieved successfully.",
        data=res,
        errors=None,
    )


@router.put(
    "/notifications/{id}/read",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Mark notification as read",
)
async def mark_read(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Mark a notification as read. Admin and HR only."""
    await service.mark_notification_read(id)
    return APIResponse[None](
        success=True,
        message="Notification marked as read.",
        data=None,
        errors=None,
    )
