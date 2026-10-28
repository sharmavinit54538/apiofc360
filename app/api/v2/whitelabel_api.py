"""Tenant white-label domain, theme, sender and document-branding APIs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin
from app.services.whitelabel_service import WhiteLabelService

router = APIRouter(prefix="/whitelabel", tags=["White-label HRMS v2"])


class WhiteLabelUpdateRequest(BaseModel):
    custom_domain: str | None = Field(None, max_length=255)
    whitelabel_enabled: bool | None = None
    brand_display_name: str | None = Field(None, max_length=150)
    brand_primary_color: str | None = Field(None, max_length=7)
    brand_secondary_color: str | None = Field(None, max_length=7)
    brand_logo_url: str | None = Field(None, max_length=500)
    brand_favicon_url: str | None = Field(None, max_length=500)
    email_sender_name: str | None = Field(None, max_length=150)
    email_sender_address: str | None = Field(None, max_length=255)
    email_reply_to: str | None = Field(None, max_length=255)
    branded_pdf_header_text: str | None = Field(None, max_length=300)


def _translate(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def get_whitelabel(claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await WhiteLabelService(db).get(company_id(claims))
    except LookupError as exc:
        _translate(exc)
    return ok(data, "White-label settings retrieved.")


@router.put("")
async def update_whitelabel(body: WhiteLabelUpdateRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await WhiteLabelService(db).update(company_id(claims), body.model_dump(exclude_unset=True))
    except (LookupError, ValueError) as exc:
        _translate(exc)
    return ok(data, "White-label settings updated.")


@router.get("/preview.pdf")
async def preview_whitelabel_pdf(claims: Claims, db: Session):
    require_admin(claims)
    try:
        content = await WhiteLabelService(db).preview_pdf(company_id(claims))
    except LookupError as exc:
        _translate(exc)
    return Response(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=whitelabel-preview.pdf"},
    )
