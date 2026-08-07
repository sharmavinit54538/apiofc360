"""Recruitment Vendors read endpoint controllers."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import RecruitmentVendorResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/vendors")


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentVendorResponse],
    summary="Retrieve recruitment vendor agency details",
)
async def get_vendor(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[RecruitmentVendorResponse]:
    """Get recruitment vendor agency details. Admin and HR only."""
    vendor = await service.get_vendor(id)
    return APIResponse[RecruitmentVendorResponse](
        success=True,
        message="Vendor details retrieved successfully.",
        data=vendor,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List registered recruitment vendors",
)
async def list_vendors(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
) -> APIResponse[dict]:
    """List recruitment vendors. Admin and HR only."""
    res = await service.list_vendors(page, limit)
    return APIResponse[dict](
        success=True,
        message="Recruitment vendors list retrieved successfully.",
        data=res,
        errors=None,
    )
