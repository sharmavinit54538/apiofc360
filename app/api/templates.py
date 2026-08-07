"""Document Templates API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.document import (
    TemplateCreate,
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
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_template(user_id, payload)
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
    """Retrieve list of all template schemas."""
    res = await service.list_templates()
    return APIResponse[list[TemplateResponse]](
        success=True,
        message="Document templates retrieved.",
        data=res,
        errors=None,
    )

@router.post(
    "/{id}/generate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[str],
    summary="Generate document from template for employee",
)
async def generate_document(
    id: uuid.UUID,
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[str]:
    """Generate string content from a template replacing all placeholders. Admin and HR only."""
    res = await service.generate_document_from_template(id, employee_id)
    return APIResponse[str](
        success=True,
        message="Document content generated successfully.",
        data=res,
        errors=None,
    )
