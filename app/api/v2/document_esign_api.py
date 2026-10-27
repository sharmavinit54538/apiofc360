"""Canonical HR letters and built-in/provider e-sign APIs."""
from __future__ import annotations

import base64
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.departments import require_admin_or_hr
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.schemas.auth import APIResponse
from app.services.esign_service import ESignService
from app.services.letter_service import CANONICAL_LETTER_NAMES, LetterService

router = APIRouter(prefix="/documents", tags=["HR Letters & E-sign v2"])
ADMIN_ROLES = {"super_admin", "hr_admin", "it_admin", "executive"}


class ESignRequestPayload(BaseModel):
    signer_user_id: uuid.UUID
    provider: Literal["BUILT_IN", "DOCUSIGN", "LEEGALITY", "docusign", "leegality", "built_in"] = "BUILT_IN"
    method: Literal["OTP", "SIGNATURE_PAD", "PROVIDER", "otp", "signature_pad", "provider"] = "OTP"


class ESignSignPayload(BaseModel):
    otp: str | None = Field(None, min_length=6, max_length=6)
    signature_data: str | None = None
    device_info: str | None = Field(None, max_length=255)


class LetterGeneratePayload(BaseModel):
    employee_id: uuid.UUID
    fields: dict[str, Any] = Field(default_factory=dict)
    save: bool = True


def _company_id(claims: dict) -> uuid.UUID | None:
    raw = claims.get("company_id")
    return uuid.UUID(str(raw)) if raw else None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/letters/types", response_model=APIResponse[list[dict[str, str]]])
async def list_letter_types(claims: Annotated[dict, Depends(get_current_user_claims)]):
    return APIResponse(success=True, message="Canonical letter types retrieved.", data=[
        {"template_name": name, "letter_type": name.upper().replace(" ", "_")} for name in CANONICAL_LETTER_NAMES
    ], errors=None)


@router.post("/letters/{letter_type}/generate", response_model=APIResponse[dict[str, Any]])
async def generate_letter(
    letter_type: str, payload: LetterGeneratePayload,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        result = await LetterService(db).generate_letter(
            letter_type, payload.employee_id, company_id=_company_id(claims), fields=payload.fields,
            actor_id=uuid.UUID(claims["sub"]), save=payload.save,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf_bytes = result.pop("pdf_bytes")
    result.pop("fields", None)
    if not payload.save:
        result["pdf_base64"] = base64.b64encode(pdf_bytes).decode("ascii")
    else:
        result["download_url"] = f"/api/documents/{result['document_id']}/download"
    return APIResponse(success=True, message="Letter rendered as PDF.", data=result, errors=None)


@router.post("/{doc_id}/request-esign", response_model=APIResponse[dict[str, Any]], status_code=status.HTTP_201_CREATED)
async def request_esign(
    doc_id: uuid.UUID, payload: ESignRequestPayload, request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        result = await ESignService(db).request_esign(
            doc_id, payload.signer_user_id, requested_by=uuid.UUID(claims["sub"]),
            company_id=_company_id(claims), provider=payload.provider.upper(), method=payload.method.upper(),
            request_ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")[:500],
            callback_url=str(request.base_url).rstrip("/") + f"/api/v2/documents/esign/webhooks/{payload.provider.lower()}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A raw OTP is delivered to the signer and must never appear in API responses.
    result.pop("otp", None)
    return APIResponse(success=True, message="E-sign request created.", data=result, errors=None)


@router.post("/{doc_id}/sign", response_model=APIResponse[dict[str, Any]])
async def sign_document(
    doc_id: uuid.UUID, payload: ESignSignPayload, request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        result = await ESignService(db).sign_document(
            doc_id, uuid.UUID(claims["sub"]), otp=payload.otp, signature_data=payload.signature_data,
            signer_ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")[:500],
            device_info=payload.device_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Document signed and audit certificate created.", data=result, errors=None)


async def _assert_certificate_access(db: AsyncSession, doc_id: uuid.UUID, claims: dict) -> None:
    doc = await db.get(EmployeeDocument, doc_id)
    if doc is None or doc.is_deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    role = str(claims.get("role") or "").lower()
    if role in ADMIN_ROLES:
        employee = await db.get(Employee, doc.employee_id)
        if role != "super_admin" and (employee is None or str(employee.company_id) != str(claims.get("company_id"))):
            raise HTTPException(status_code=404, detail="Document not found.")
        return
    employee = (await db.execute(select(Employee).where(Employee.user_id == uuid.UUID(claims["sub"])))).scalar_one_or_none()
    if employee is None or employee.id != doc.employee_id:
        raise HTTPException(status_code=403, detail="You are not allowed to access this audit certificate.")


@router.get("/{doc_id}/audit-certificate")
async def get_audit_certificate(
    doc_id: uuid.UUID, claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)], format: str = Query("json", pattern="^(json|pdf)$"),
):
    await _assert_certificate_access(db, doc_id, claims)
    try:
        certificate, pdf = await ESignService(db).get_audit_certificate(doc_id, company_id=_company_id(claims))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if format == "pdf":
        return Response(content=pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="esign_audit_{doc_id}.pdf"'
        })
    return APIResponse(success=True, message="E-sign audit certificate retrieved.", data=certificate, errors=None)


@router.post("/esign/webhooks/{provider}", response_model=APIResponse[dict[str, Any]])
@router.post("/webhooks/esign/{provider}", response_model=APIResponse[dict[str, Any]], include_in_schema=False)
async def provider_webhook(
    provider: str, request: Request, db: Annotated[AsyncSession, Depends(get_db_session)],
    x_webhook_signature: Annotated[str | None, Header()] = None,
    docusign_signature: Annotated[str | None, Header(alias="X-DocuSign-Signature-1")] = None,
    leegality_signature: Annotated[str | None, Header(alias="X-Leegality-Signature")] = None,
):
    raw = await request.body()
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        result = await ESignService(db).process_provider_webhook(
            provider, payload, raw_body=raw,
            webhook_secret=x_webhook_signature or docusign_signature or leegality_signature,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Provider webhook processed.", data=result, errors=None)


__all__ = ["router"]
