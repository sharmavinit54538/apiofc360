"""Recruitment Vendors delete endpoint controller."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/vendors")


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete recruitment vendor agency",
)
async def delete_vendor(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Delete recruitment vendor agency record. Admin and HR only."""
    await service.delete_vendor(id)
    return APIResponse[None](
        success=True,
        message="Vendor agency deleted successfully.",
        data=None,
        errors=None,
    )
