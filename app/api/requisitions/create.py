"""Job Requisitions create and approve endpoints."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    JobRequisitionCreate,
    JobRequisitionResponse,
    RequisitionApproval,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/requisitions")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[JobRequisitionResponse],
    summary="Create a new job requisition",
)
async def create_requisition(
    payload: JobRequisitionCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobRequisitionResponse]:
    """Request a new job requisition. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    req = await service.create_requisition(user_id, payload)
    return APIResponse[JobRequisitionResponse](
        success=True,
        message="Job requisition submitted successfully.",
        data=req,
        errors=None,
    )


@router.post(
    "/{id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobRequisitionResponse],
    summary="Approve or reject a job requisition",
)
async def approve_requisition(
    id: uuid.UUID,
    payload: RequisitionApproval,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobRequisitionResponse]:
    """Approve or reject a job requisition. Convert to Job posting if approved. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    req = await service.approve_requisition(user_id, id, payload.approve)
    msg = "Job requisition approved and job template created." if payload.approve else "Job requisition rejected."
    return APIResponse[JobRequisitionResponse](
        success=True,
        message=msg,
        data=req,
        errors=None,
    )
