"""Offer Letter API v2 — AI-generated PDF/DOCX offer letters."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.offer_letter_service import (
    OfferLetterContext,
    OfferLetterService,
    get_offer_letter_service,
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/offer-letters", tags=["Offer Letters AI v2"])


class GenerateOfferRequest(BaseModel):
    candidate_name: str = Field(..., min_length=2)
    position: str
    department: str
    salary: str = Field(..., description="e.g. '₹18,00,000 LPA' or '$120,000/year'")
    joining_date: str = Field(..., description="e.g. '2025-08-15' or 'August 15, 2025'")
    company_name: str
    reporting_to: str = "Hiring Manager"
    location: str = "Head Office"
    benefits: list[str] = Field(default_factory=list)
    employment_type: str = "Full-Time"
    probation_months: int = Field(3, ge=0, le=12)
    offer_expiry_days: int = Field(7, ge=1, le=30)
    additional_terms: str = ""
    hr_signatory: str = "HR Department"
    use_ai_content: bool = True
    export_format: str = Field("pdf", description="pdf | docx | text")
    model: str | None = None


@router.post(
    "/generate",
    response_model=APIResponse[dict],
    summary="Generate an AI-powered offer letter",
    description="""
Generate a professional offer letter for a candidate using AI.

**Formats:** PDF (via weasyprint), DOCX (via python-docx), or plain text.

**AI Enhancement:** When `use_ai_content=true`, Ollama LLM generates professional,
personalized offer letter content. Falls back to template if AI unavailable.

**Returns:** Letter content + download path for the generated file.
""",
)
async def generate_offer_letter(
    body: GenerateOfferRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict]:
    """Generate and save an offer letter."""
    ctx = OfferLetterContext(
        candidate_name=body.candidate_name,
        position=body.position,
        department=body.department,
        salary=body.salary,
        joining_date=body.joining_date,
        company_name=body.company_name,
        reporting_to=body.reporting_to,
        location=body.location,
        benefits=body.benefits or None,
        employment_type=body.employment_type,
        probation_months=body.probation_months,
        offer_expiry_days=body.offer_expiry_days,
        additional_terms=body.additional_terms,
        hr_signatory=body.hr_signatory,
    )

    service = get_offer_letter_service()

    # Generate content
    letter_content = await service.generate_offer_letter(
        context=ctx,
        use_ai_content=body.use_ai_content,
        model=body.model,
    )

    # Export to requested format
    export_fmt = body.export_format.lower()
    file_path = None

    try:
        if export_fmt == "pdf":
            file_path = await service.export_pdf(letter_content["full_letter_text"], ctx)
        elif export_fmt == "docx":
            file_path = service.export_docx(letter_content["full_letter_text"], ctx)
        else:
            # Plain text
            from app.core.config import settings
            import uuid as _uuid
            txt_name = f"offer_letter_{_uuid.uuid4().hex[:8]}.txt"
            file_path = os.path.join(settings.OFFER_LETTER_DIR, txt_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(letter_content["full_letter_text"])
    except Exception as exc:
        logger.error("Offer letter export failed: %s", exc)
        file_path = None

    return APIResponse[dict](
        success=True,
        message="Offer letter generated successfully.",
        data={
            "subject": letter_content["subject"],
            "full_letter_text": letter_content["full_letter_text"],
            "key_terms": letter_content.get("key_terms", {}),
            "export_format": export_fmt,
            "file_path": file_path,
            "download_available": file_path is not None and os.path.exists(file_path),
        },
        errors=None,
    )


@router.get(
    "/download/{filename}",
    summary="Download a generated offer letter file",
    responses={
        200: {"description": "File download"},
        404: {"description": "File not found"},
    },
)
async def download_offer_letter(
    filename: str,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> FileResponse:
    """Download a previously generated offer letter PDF/DOCX/TXT file."""
    from app.core.config import settings

    # Security: prevent path traversal
    safe_name = os.path.basename(filename)
    if not safe_name.startswith("offer_letter_"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(settings.OFFER_LETTER_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Offer letter file not found")

    ext = os.path.splitext(safe_name)[1].lower()
    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
    }

    return FileResponse(
        path=file_path,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=safe_name,
    )
