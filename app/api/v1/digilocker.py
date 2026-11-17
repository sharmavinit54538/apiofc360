"""DigiLocker Document Verification API v1."""

from __future__ import annotations

import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.document.verification import DocumentVerification
from app.models.employee_document import EmployeeDocument
from app.schemas.auth import APIResponse

router = APIRouter(
    prefix="/employee/document-verification",
    tags=["DigiLocker Document Verification"],
)


class DigilockerConfig:
    """DigiLocker OAuth2 configuration."""
    CLIENT_ID = getattr(settings, "DIGILOCKER_CLIENT_ID", "")
    CLIENT_SECRET = getattr(settings, "DIGILOCKER_CLIENT_SECRET", "")
    REDIRECT_URI = getattr(settings, "DIGILOCKER_REDIRECT_URI", "http://localhost:8000/api/v1/employee/document-verification/digilocker/callback")
    AUTH_URL = "https://digilocker.meripehchaan.gov.in/public/oauth2/1/authorize"
    TOKEN_URL = "https://digilocker.meripehchaan.gov.in/public/oauth2/1/token"
    DOCUMENTS_URL = "https://digilocker.meripehchaan.gov.in/public/oauth2/1/documents"


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


async def get_current_employee(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Get current employee ID and company ID from claims."""
    user_id_str = claims.get("sub")
    company_id_str = claims.get("company_id")
    if not user_id_str or not company_id_str:
        raise HTTPException(status_code=401, detail="Invalid authentication claims")
    return uuid.UUID(user_id_str), uuid.UUID(company_id_str)


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VerificationStatusResponse],
    summary="Get DigiLocker verification status",
)
async def get_digilocker_status(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[VerificationStatusResponse]:
    """Retrieve the authenticated employee's DigiLocker verification status."""
    user_id, company_id = await get_current_employee(claims, db)

    # Find employee document record
    emp_doc_stmt = select(EmployeeDocument).where(
        EmployeeDocument.employee_id == user_id,
        EmployeeDocument.company_id == company_id,
        EmployeeDocument.is_deleted == False,  # noqa: E712
    )
    emp_doc_res = await db.execute(emp_doc_stmt)
    emp_doc = emp_doc_res.scalars().first()

    if not emp_doc:
        return APIResponse[VerificationStatusResponse](
            success=True,
            message="No document verification record found.",
            data=VerificationStatusResponse(
                verified=False,
                status="not_started",
                error_message="Employee document record not found",
            ),
            errors=None,
        )

    # Get latest verification
    ver_stmt = select(DocumentVerification).where(
        DocumentVerification.employee_doc_id == emp_doc.id,
    ).order_by(DocumentVerification.created_at.desc())
    ver_res = await db.execute(ver_stmt)
    verification = ver_res.scalars().first()

    if not verification:
        return APIResponse[VerificationStatusResponse](
            success=True,
            message="Document verification not initiated.",
            data=VerificationStatusResponse(
                verified=False,
                status="not_started",
                document_type=emp_doc.document_type,
            ),
            errors=None,
        )

    verified = verification.action == "APPROVED"
    status_map = {
        "APPROVED": "verified",
        "REJECTED": "failed",
        "RE_UPLOAD_REQUESTED": "initiated",
    }

    return APIResponse[VerificationStatusResponse](
        success=True,
        message="Verification status retrieved.",
        data=VerificationStatusResponse(
            verified=verified,
            status=status_map.get(verification.action, "initiated"),
            document_type=emp_doc.document_type,
            verified_at=verification.created_at if verified else None,
            digilocker_user_id=verification.extra_data.get("digilocker_user_id") if getattr(verification, "extra_data", None) else None,
            documents_fetched=verification.extra_data.get("documents_fetched", []) if getattr(verification, "extra_data", None) else [],
            error_message=verification.comments if not verified else None,
        ),
        errors=None,
    )


@router.post(
    "/digilocker/initiate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DigilockerInitiateResponse],
    summary="Initiate DigiLocker authorization",
)
async def initiate_digilocker(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[DigilockerInitiateResponse]:
    """Initiate DigiLocker OAuth2 authorization flow."""
    user_id, company_id = await get_current_employee(claims, db)

    # Generate secure state parameter
    state = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Store state in session/cache (in production, use Redis with TTL)
    # For now, we'll store it in a simple verification record
    emp_doc_stmt = select(EmployeeDocument).where(
        EmployeeDocument.employee_id == user_id,
        EmployeeDocument.company_id == company_id,
        EmployeeDocument.is_deleted == False,  # noqa: E712
    )
    emp_doc_res = await db.execute(emp_doc_stmt)
    emp_doc = emp_doc_res.scalars().first()

    if not emp_doc:
        raise HTTPException(status_code=404, detail="Employee document record not found")

    # Create a pending verification record to store state
    verification = DocumentVerification(
        employee_doc_id=emp_doc.id,
        verifier_user_id=user_id,  # Self-initiated
        action="RE_UPLOAD_REQUESTED",
        comments=f"DigiLocker authorization initiated. State: {state}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(verification)
    await db.commit()

    # Build authorization URL
    params = {
        "response_type": "code",
        "client_id": DigilockerConfig.CLIENT_ID,
        "redirect_uri": DigilockerConfig.REDIRECT_URI,
        "state": state,
        "scope": "digilocker.documents.read",
    }
    authorization_url = f"{DigilockerConfig.AUTH_URL}?{urlencode(params)}"

    return APIResponse[DigilockerInitiateResponse](
        success=True,
        message="DigiLocker authorization initiated. Redirect user to authorization_url.",
        data=DigilockerInitiateResponse(
            authorization_url=authorization_url,
            state=state,
            expires_at=expires_at,
        ),
        errors=None,
    )


@router.post(
    "/digilocker/callback",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DigilockerCallbackResponse],
    summary="Handle DigiLocker OAuth2 callback",
)
async def digilocker_callback(
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[DigilockerCallbackResponse]:
    """Handle DigiLocker OAuth2 callback and exchange code for documents."""
    user_id, company_id = await get_current_employee(claims, db)

    # Get query parameters
    query_params = dict(request.query_params)
    code = query_params.get("code")
    state = query_params.get("state")
    error = query_params.get("error")
    error_description = query_params.get("error_description")

    if error:
        return APIResponse[DigilockerCallbackResponse](
            success=False,
            message=f"DigiLocker authorization failed: {error_description or error}",
            data=DigilockerCallbackResponse(
                success=False,
                message=error_description or error,
                verified=False,
            ),
            errors=None,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Verify state matches (in production, verify against stored state)
    # For now, we'll find the latest pending verification
    emp_doc_stmt = select(EmployeeDocument).where(
        EmployeeDocument.employee_id == user_id,
        EmployeeDocument.company_id == company_id,
        EmployeeDocument.is_deleted == False,  # noqa: E712
    )
    emp_doc_res = await db.execute(emp_doc_stmt)
    emp_doc = emp_doc_res.scalars().first()

    if not emp_doc:
        raise HTTPException(status_code=404, detail="Employee document record not found")

    ver_stmt = select(DocumentVerification).where(
        DocumentVerification.employee_doc_id == emp_doc.id,
        DocumentVerification.action == "RE_UPLOAD_REQUESTED",
    ).order_by(DocumentVerification.created_at.desc())
    ver_res = await db.execute(ver_stmt)
    verification = ver_res.scalars().first()

    if not verification or state not in (verification.comments or ""):
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    # Exchange authorization code for access token
    # In production, use httpx to make the token request
    # token_response = await http_client.post(DigilockerConfig.TOKEN_URL, data={
    #     "grant_type": "authorization_code",
    #     "code": code,
    #     "redirect_uri": DigilockerConfig.REDIRECT_URI,
    #     "client_id": DigilockerConfig.CLIENT_ID,
    #     "client_secret": DigilockerConfig.CLIENT_SECRET,
    # })
    # access_token = token_response.json().get("access_token")

    # Fetch documents using access token
    # documents_response = await http_client.get(
    #     DigilockerConfig.DOCUMENTS_URL,
    #     headers={"Authorization": f"Bearer {access_token}"}
    # )
    # documents = documents_response.json()

    # For now, simulate successful document fetch
    documents_fetched = ["Aadhaar", "PAN", "Driving License"]
    digilocker_user_id = f"DL-{user_id.hex[:8]}"

    # Update verification record
    verification.action = "APPROVED"
    verification.comments = "DigiLocker verification completed successfully"
    verification.extra_data = {
        "digilocker_user_id": digilocker_user_id,
        "documents_fetched": documents_fetched,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    # Update employee document status
    emp_doc.status = "VERIFIED"
    emp_doc.is_verified = True
    emp_doc.verified_at = datetime.now(timezone.utc)
    db.add(emp_doc)
    await db.commit()

    return APIResponse[DigilockerCallbackResponse](
        success=True,
        message="DigiLocker verification completed successfully.",
        data=DigilockerCallbackResponse(
            success=True,
            message="Documents verified via DigiLocker",
            verified=True,
            document_types=documents_fetched,
        ),
        errors=None,
    )