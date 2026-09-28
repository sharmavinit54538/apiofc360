"""AI Hub — Document Generator (/api/v1/ai-hub/document-generator/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.document_generator import (
    DocumentGeneratorOverview,
    DocumentTemplatesList,
    GenerateDocumentRequest,
    GenerateDocumentResponse,
    PreviewDocumentRequest,
    PreviewDocumentResponse,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.document_generator_service import DocumentGeneratorService
from app.services.ai_hub.utils import get_company_id_from_claims

router = APIRouter(prefix="/ai-hub/document-generator", tags=["AI Hub - Document Generator"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentGeneratorService:
    return DocumentGeneratorService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DocumentGeneratorOverview],
    summary="Document Generator Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentGeneratorService, Depends(get_service)],
) -> APIResponse[DocumentGeneratorOverview]:
    """Retrieve document generator engine stats, available formats, and recent history."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_overview(company_id=company_id)
    return APIResponse[DocumentGeneratorOverview](
        success=True,
        message="Document generator overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/templates",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DocumentTemplatesList],
    summary="List Document Templates",
)
async def list_templates(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentGeneratorService, Depends(get_service)],
) -> APIResponse[DocumentTemplatesList]:
    """List all available document templates with identified placeholder fields."""
    data = await service.list_templates()
    return APIResponse[DocumentTemplatesList](
        success=True,
        message="Document templates fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[GenerateDocumentResponse],
    summary="Generate and Persist Document",
)
async def generate_document(
    payload: GenerateDocumentRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentGeneratorService, Depends(get_service)],
) -> APIResponse[GenerateDocumentResponse]:
    """Render template with variables, generate PDF/DOCX/HTML/TXT file, and persist record."""
    company_id = get_company_id_from_claims(claims)
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(user_id_raw) if user_id_raw else None

    data = await service.generate(
        company_id=company_id,
        user_id=user_id,
        payload=payload,
    )
    return APIResponse[GenerateDocumentResponse](
        success=True,
        message=f"Document '{payload.title}' generated successfully in format {data.format.upper()}.",
        data=data,
        errors=None,
    )


@router.post(
    "/preview",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PreviewDocumentResponse],
    summary="Preview Rendered Template",
)
async def preview_document(
    payload: PreviewDocumentRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentGeneratorService, Depends(get_service)],
) -> APIResponse[PreviewDocumentResponse]:
    """Render a dynamic preview of the template with substituted variables without persistence."""
    data = await service.preview(payload=payload)
    return APIResponse[PreviewDocumentResponse](
        success=True,
        message="Document preview rendered successfully.",
        data=data,
        errors=None,
    )
