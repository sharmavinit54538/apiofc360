"""Document Templates API routes."""

from __future__ import annotations

from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.core.exceptions import AppException
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.document import (
    TemplateCreate,
    TemplateGenerateRequest,
    TemplateResponse,
)
from app.services.document_service import DocumentService, get_document_service

router = APIRouter(prefix="/document-templates", tags=["Document Template Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[TemplateResponse],
    summary="Create a new document template",
)
async def create_template(
    payload: TemplateCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[TemplateResponse]:
    """Create a new document template with placeholders. Admin and HR only."""
    role = (claims.get("role") or "").lower()
    company_id_raw = claims.get("company_id")
    if role != "super_admin" and not company_id_raw:
        raise AppException(message="Tenant context required.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_template(user_id, payload, company_id=company_id)
    return APIResponse[TemplateResponse](
        success=True,
        message="Document template created successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[TemplateResponse]],
    summary="List all document templates",
)
async def list_templates(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[list[TemplateResponse]]:
    """Retrieve list of all template schemas scoped to tenant."""
    role = (claims.get("role") or "").lower()
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw and role != "super_admin" else None

    res = await service.list_templates(company_id=company_id)
    return APIResponse[list[TemplateResponse]](
        success=True,
        message="Document templates retrieved.",
        data=res,
        errors=None,
    )


@router.post(
    "/{id}/generate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict[str, Any]],
    summary="Generate document from template for employee",
)
async def generate_document(
    id: uuid.UUID,
    payload: TemplateGenerateRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[dict[str, Any]]:
    """Generate content from a template replacing all placeholders. Admin and HR only (Rule 3.7)."""
    res = await service.generate_document_from_template(
        template_uuid=id,
        employee_uuid=payload.employee_id,
        caller_claims=claims,
        extra_fields=payload.fields,
        save_as_document=payload.save_as_document,
    )
    return APIResponse[dict[str, Any]](
        success=True,
        message="Document content generated successfully.",
        data=res,
        errors=None,
    )
