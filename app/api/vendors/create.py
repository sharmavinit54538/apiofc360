"""Recruitment Vendors create endpoint controller."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    RecruitmentVendorCreate,
    RecruitmentVendorResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/vendors")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[RecruitmentVendorResponse],
    summary="Create a recruitment vendor agency",
)
async def create_vendor(
    payload: RecruitmentVendorCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[RecruitmentVendorResponse]:
    """Register a recruitment vendor agency. Admin and HR only."""
    vendor = await service.create_vendor(payload)
    return APIResponse[RecruitmentVendorResponse](
        success=True,
        message="Recruitment vendor agency registered successfully.",
        data=vendor,
        errors=None,
    )
