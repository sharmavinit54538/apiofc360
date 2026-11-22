"""Tenant-bound DigiLocker OAuth authorization and evidence-backed verification."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_employee as resolve_employee
from app.models.document.verification import DocumentVerification
from app.models.employee_document import EmployeeDocument
from app.schemas.auth import APIResponse
from app.services.digilocker_service import configured, fetch_evidence, DigiLockerFailure

router = APIRouter(prefix="/employee/document-verification", tags=["DigiLocker Document Verification"])

class VerificationStatusResponse(BaseModel):
    verified: bool
    status: str  # not_started, initiated, verified, failed, expired
    document_type: str | None = None
    verified_at: datetime | None = None
    digilocker_user_id: str | None = None
    documents_fetched: list[str] = Field(default_factory=list)
    error_message: str | None = None


class DigilockerInitiateResponse(BaseModel):
    authorization_url: HttpUrl
    state: str
    expires_at: datetime


class DigilockerCallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)
    error: str | None = None
    error_description: str | None = None


class DigilockerCallbackResponse(BaseModel):
    success: bool
    message: str
    verified: bool
    document_types: list[str] = Field(default_factory=list)


async def _document(claims: dict, db: AsyncSession) -> EmployeeDocument | None:
    employee = await resolve_employee(claims, db)
    result = await db.execute(select(EmployeeDocument).where(
        EmployeeDocument.employee_id == employee.id,
        EmployeeDocument.is_deleted.is_(False),
    ).order_by(EmployeeDocument.created_at.desc()))
    return result.scalars().first()


async def _latest(doc: EmployeeDocument, db: AsyncSession, *, lock=False) -> DocumentVerification | None:
    stmt = select(DocumentVerification).where(
        DocumentVerification.employee_doc_id == doc.id,
        DocumentVerification.extra_data["provider"].as_string() == "digilocker",
    ).order_by(DocumentVerification.created_at.desc()).limit(1)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalars().first()


@router.get("/status", response_model=APIResponse[VerificationStatusResponse])
async def get_digilocker_status(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    doc = await _document(claims, db)
    verification = await _latest(doc, db) if doc else None
    evidence = (verification.extra_data or {}) if verification else {}
    verified = bool(verification and verification.action == "APPROVED" and evidence.get("integrity_verified") and evidence.get("sha256"))
    state = "verified" if verified else ("failed" if verification and verification.action == "REJECTED" else "initiated" if verification else "not_started")
    if state == "initiated" and evidence.get("expires_at") and datetime.fromisoformat(evidence["expires_at"]) < datetime.now(timezone.utc):
        state = "expired"
    return APIResponse(success=True, message="Verification status retrieved.", data=VerificationStatusResponse(
        verified=verified, status=state, document_type=doc.document_type if doc else None,
        verified_at=datetime.fromisoformat(evidence["verified_at"]) if verified else None,
        digilocker_user_id=evidence.get("digilocker_user_id"), documents_fetched=evidence.get("documents_fetched", []),
        error_message=verification.comments if verification and not verified else None,
    ))


@router.post("/digilocker/initiate", response_model=APIResponse[DigilockerInitiateResponse])
async def initiate_digilocker(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    doc = await _document(claims, db)
    if not doc:
        raise HTTPException(404, "Employee document record not found")
    oauth_state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    verification = DocumentVerification(
        employee_doc_id=doc.id, verifier_user_id=uuid.UUID(claims["sub"]),
        action="RE_UPLOAD_REQUESTED" if configured() else "REJECTED",
        comments="DigiLocker authorization pending." if configured() else "DigiLocker credentials are not configured.",
        extra_data={"provider": "digilocker", "state_hash": hashlib.sha256(oauth_state.encode()).hexdigest(),
                    "expires_at": expires.isoformat(), "code_verifier": verifier},
    )
    db.add(verification)
    await db.commit()
    if not configured():
        raise HTTPException(503, "DigiLocker credentials are not configured; verification has not been completed.")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": settings.DIGILOCKER_CLIENT_ID,
              "redirect_uri": settings.DIGILOCKER_REDIRECT_URI, "state": oauth_state,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    return APIResponse(success=True, message="DigiLocker authorization initiated.", data=DigilockerInitiateResponse(
        authorization_url=f"{settings.DIGILOCKER_API_BASE_URL.rstrip('/')}/1/authorize?{urlencode(params)}",
        state=oauth_state, expires_at=expires,
    ))


@router.post("/digilocker/callback", response_model=APIResponse[DigilockerCallbackResponse])
async def digilocker_callback(
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    params = dict(request.query_params)
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
        if isinstance(payload, dict):
            params.update(payload)
    state_value, code = params.get("state"), params.get("code")
    if not isinstance(state_value, str) or not state_value:
        raise HTTPException(400, "Missing state parameter")
    doc = await _document(claims, db)
    if not doc:
        raise HTTPException(404, "Employee document record not found")
    verification = await _latest(doc, db, lock=True)
    data = dict(verification.extra_data or {}) if verification else {}
    if not verification or not hmac.compare_digest(data.get("state_hash", ""), hashlib.sha256(state_value.encode()).hexdigest()):
        raise HTTPException(400, "Invalid or expired state parameter")
    if verification.action == "APPROVED" and data.get("integrity_verified"):
        return APIResponse(success=True, message="DigiLocker verification already completed.", data=DigilockerCallbackResponse(
            success=True, message="Documents verified via DigiLocker", verified=True, document_types=data.get("documents_fetched", [])))
    if verification.action != "RE_UPLOAD_REQUESTED" or datetime.fromisoformat(data["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired state parameter; initiate authorization again.")
    try:
        if params.get("error"):
            raise DigiLockerFailure("DigiLocker authorization was denied or cancelled.")
        if not isinstance(code, str) or not code:
            raise HTTPException(400, "Missing code parameter")
        evidence = await fetch_evidence(code=code, code_verifier=data["code_verifier"], document_type=doc.document_type)
    except DigiLockerFailure as exc:
        data.pop("code_verifier", None)
        verification.extra_data = data
        verification.action = "REJECTED"
        verification.comments = str(exc)
        await db.commit()
        return APIResponse(success=False, message=str(exc), data=DigilockerCallbackResponse(success=False, message=str(exc), verified=False))
    now = datetime.now(timezone.utc)
    data.pop("code_verifier", None)
    verification.extra_data = {**data, **evidence, "verified_at": now.isoformat()}
    verification.action = "APPROVED"
    verification.comments = "DigiLocker issued document retrieved and integrity verified."
    doc.status, doc.is_verified, doc.verified_at = "VERIFIED", True, now
    doc.verified_by = uuid.UUID(claims["sub"])
    await db.commit()
    return APIResponse(success=True, message="DigiLocker verification completed.", data=DigilockerCallbackResponse(
        success=True, message="Documents verified via DigiLocker", verified=True, document_types=evidence["documents_fetched"]))
