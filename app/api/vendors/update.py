"""Recruitment Vendors update endpoint controller."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    RecruitmentVendorUpdate,
    RecruitmentVendorResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/vendors")


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentVendorResponse],
    summary="Update recruitment vendor agency",
)
async def update_vendor(
    id: uuid.UUID,
    payload: RecruitmentVendorUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[RecruitmentVendorResponse]:
    """Update recruitment vendor agency profile. Admin and HR only."""
    vendor = await service.update_vendor(id, payload)
    return APIResponse[RecruitmentVendorResponse](
        success=True,
        message="Vendor details updated successfully.",
        data=vendor,
        errors=None,
    )
