"""Job Requisitions read endpoints."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import JobRequisitionResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/requisitions")


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobRequisitionResponse],
    summary="Retrieve job requisition details",
)
async def get_requisition(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobRequisitionResponse]:
    """Get requisition details. Admin and HR only."""
    req = await service.get_requisition(id)
    return APIResponse[JobRequisitionResponse](
        success=True,
        message="Job requisition retrieved successfully.",
        data=req,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List job requisitions with status filter",
)
async def list_requisitions(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
) -> APIResponse[dict]:
    """List job requisitions. Admin and HR only."""
    res = await service.list_requisitions(status, page, limit)
    return APIResponse[dict](
        success=True,
        message="Job requisitions retrieved successfully.",
        data=res,
        errors=None,
    )
