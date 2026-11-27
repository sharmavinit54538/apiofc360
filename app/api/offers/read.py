"""Job offer reading/listing endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.rbac import require_tenant_admin
from app.schemas.auth import APIResponse
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/offers")


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List all offers with pagination",
)
async def list_offers(
    claims: Annotated[dict, Depends(require_tenant_admin)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
) -> APIResponse[dict]:
    """List all released offers. Admin and HR only."""
    res = await service.list_offers(page, limit)
    return APIResponse[dict](
        success=True,
        message="Offers retrieved successfully.",
        data=res,
        errors=None,
    )
