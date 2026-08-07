"""Recruitment Analytics and Notifications API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr_or_manager, require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    RecruitmentNotificationResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/recruitment", tags=["Recruitment Analytics & Alerts"])


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get recruitment funnel and pipeline analytics",
)
async def get_analytics(
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[dict]:
    """Retrieve funnel, trend, and source effectiveness analytics. Admin, HR and Manager."""
    company_id_raw = claims.get("company_id") if isinstance(claims, dict) else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    res = await service.get_recruitment_analytics(company_id=company_id)
    return APIResponse[dict](
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
