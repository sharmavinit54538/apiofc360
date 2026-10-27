"""DPDP self-service APIs and privileged sensitive-PII disclosure."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_hr_admin
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.audit_log import PII_UNMASK_ACCESS, create_audit_entry
from app.models.dpdp_compliance import (
    ConsentPurposeCode,
    ConsentStatus,
    DataConsentLedger,
    DataSubjectRequestStatus,
)
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.user.role import RoleEnum
from app.schemas.auth import APIResponse
from app.services.dpdp_service import DPDPNotFoundError, DPDPService


router = APIRouter(prefix="/dpdp", tags=["DPDP Compliance"])
employee_pii_router = APIRouter(prefix="/employees", tags=["Sensitive Employee PII"])


class ConsentCreateRequest(BaseModel):
    employee_id: uuid.UUID | None = None
    purpose_code: ConsentPurposeCode
    policy_version: str = Field(min_length=1, max_length=64)
    consent_status: ConsentStatus = ConsentStatus.GRANTED

    @field_validator("purpose_code", "consent_status", mode="before")
    @classmethod
    def normalize_enum(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class DataExportRequest(BaseModel):
    employee_id: uuid.UUID | None = None
    format: Literal["JSON", "ZIP"] = "ZIP"

    @field_validator("format", mode="before")
    @classmethod
    def normalize_format(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class ErasureRequestCreate(BaseModel):
    employee_id: uuid.UUID | None = None


def _company_id(claims: dict) -> uuid.UUID:
    raw = claims.get("company_id")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A company-scoped account is required for DPDP operations.",
        )
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid company association.") from exc


def _actor_id(claims: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims.get("sub")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authenticated user.") from exc


def _is_privileged(claims: dict) -> bool:
    role = RoleEnum.from_str(str(claims.get("role") or ""))
    return role in {RoleEnum.HR_ADMIN, RoleEnum.SUPER_ADMIN}


async def _target_employee(
    requested_employee_id: uuid.UUID | None,
    claims: dict,
    service: DPDPService,
) -> Employee:
    company_id = _company_id(claims)
    actor_id = _actor_id(claims)
    if requested_employee_id is None:
        return await service.get_employee_for_user(actor_id, company_id)

    # Resolve in the tenant first: foreign ids always produce the same 404 as
    # unknown ids, including when the caller is not privileged.
    target = await service.get_employee(requested_employee_id, company_id)
    if not _is_privileged(claims):
        own = await service.get_employee_for_user(actor_id, company_id)
        if own.id != target.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only submit DPDP requests for your own personal data.",
            )
    return target


def _consent_dict(entry: DataConsentLedger) -> dict:
    return {
        "id": str(entry.id),
        "employee_id": str(entry.employee_id),
        "user_id": str(entry.user_id) if entry.user_id else None,
        "company_id": str(entry.company_id) if entry.company_id else None,
        "purpose_code": str(getattr(entry.purpose_code, "value", entry.purpose_code)),
        "policy_version": entry.policy_version,
        "consent_status": str(getattr(entry.consent_status, "value", entry.consent_status)),
        "ip_address": entry.ip_address,
        "user_agent": entry.user_agent,
        "granted_at": entry.granted_at.isoformat() if entry.granted_at else None,
        "withdrawn_at": entry.withdrawn_at.isoformat() if entry.withdrawn_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _not_found(exc: DPDPNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/consents", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict])
async def create_consent(
    payload: ConsentCreateRequest,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = DPDPService(db)
    try:
        employee = await _target_employee(payload.employee_id, claims, service)
        entry = await service.record_consent(
            employee_id=employee.id,
            company_id=_company_id(claims),
            user_id=employee.user_id or _actor_id(claims),
            purpose_code=payload.purpose_code,
            policy_version=payload.policy_version,
            consent_status=payload.consent_status,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return APIResponse[dict](
        success=True,
        message="Consent ledger entry recorded.",
        data=_consent_dict(entry),
        errors=None,
    )


@router.get("/consents/me", response_model=APIResponse[list[dict]])
async def get_my_consents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = DPDPService(db)
    try:
        entries = await service.list_consents_for_user(
            user_id=_actor_id(claims), company_id=_company_id(claims)
        )
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc
    return APIResponse[list[dict]](
        success=True,
        message="Consent ledger retrieved.",
        data=[_consent_dict(entry) for entry in entries],
        errors=None,
    )


@router.post("/data-export")
async def export_personal_data(
    payload: DataExportRequest | None = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    payload = payload or DataExportRequest()
    service = DPDPService(db)
    try:
        employee = await _target_employee(payload.employee_id, claims, service)
        data = await service.export_employee_data(
            employee_id=employee.id,
            company_id=_company_id(claims),
            actor_id=_actor_id(claims),
        )
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc

    if payload.format == "JSON":
        content = service.export_as_json(data)
        media_type = "application/json"
        filename = f"dpdp-export-{employee.id}.json"
    else:
        content = service.export_as_zip(data)
        media_type = "application/zip"
        filename = f"dpdp-export-{employee.id}.zip"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/erasure-requests", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict])
async def create_erasure_request(
    payload: ErasureRequestCreate | None = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    payload = payload or ErasureRequestCreate()
    service = DPDPService(db)
    try:
        employee = await _target_employee(payload.employee_id, claims, service)
        data_request = await service.create_erasure_request(
            employee_id=employee.id, company_id=_company_id(claims)
        )
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc
    return APIResponse[dict](
        success=True,
        message="Erasure request created for review.",
        data=service._request_summary(data_request),
        errors=None,
    )


@router.post("/erasure-requests/{request_id}/execute", response_model=APIResponse[dict])
async def execute_erasure_request(
    request_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_hr_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = DPDPService(db)
    try:
        data_request = await service.execute_erasure_request(
            request_id=request_id,
            company_id=_company_id(claims),
            reviewer_id=_actor_id(claims),
        )
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    summary = service._request_summary(data_request)
    if data_request.status == DataSubjectRequestStatus.REJECTED_STATUTORY_HOLD.value:
        envelope = APIResponse[dict](
            success=False,
            message="Erasure is blocked by the statutory payroll/tax retention period.",
            data=summary,
            errors=[{"field": None, "message": "STATUTORY_HOLD"}],
        )
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=jsonable_encoder(envelope))
    return APIResponse[dict](
        success=True,
        message="Non-statutory personal data erased; statutory ledger totals preserved.",
        data=summary,
        errors=None,
    )


@employee_pii_router.get("/{employee_id}/sensitive-pii", response_model=APIResponse[dict])
async def get_sensitive_employee_pii(
    employee_id: uuid.UUID,
    request: Request,
    response: Response,
    claims: Annotated[dict, Depends(require_hr_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Unmask statutory identifiers only after durable privileged auditing."""

    company_id = _company_id(claims)
    actor_id = _actor_id(claims)
    service = DPDPService(db)
    try:
        employee = await service.get_employee(employee_id, company_id)
    except DPDPNotFoundError as exc:
        raise _not_found(exc) from exc

    bank_result = await db.execute(
        select(EmployeeBankAccount)
        .where(EmployeeBankAccount.employee_id == employee.id)
        .execution_options(bypass_tenant=True)
    )
    accounts = list(bank_result.scalars().all())

    # The event intentionally contains metadata only—never the values being
    # disclosed. Committing before constructing the response guarantees that a
    # failed audit write prevents the unmask operation.
    audit = create_audit_entry(
        action=PII_UNMASK_ACCESS,
        company_id=company_id,
        user_id=actor_id,
        actor_id=str(actor_id),
        entity_type="Employee",
        entity_id=str(employee.id),
        email=str(claims.get("email") or "") or None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details="Privileged sensitive PII access for statutory filing.",
        metadata_json=json.dumps(
            {"purpose": "STATUTORY_FILING", "employee_id": str(employee.id)},
            separators=(",", ":"),
        ),
    )
    db.add(audit)
    await db.commit()

    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return APIResponse[dict](
        success=True,
        message="Sensitive PII disclosed for statutory filing; access has been audited.",
        data={
            "employee_id": str(employee.id),
            "aadhaar_number": employee.aadhaar_number,
            "pan_number": employee.pan_number,
            "uan_number": employee.uan_number,
            "passport_number": employee.passport_number,
            "voter_id": employee.voter_id,
            "bank_accounts": [
                {
                    "id": str(account.id),
                    "bank_name": account.bank_name,
                    "account_holder_name": account.account_holder_name,
                    "account_number": account.account_number,
                    "ifsc_code": account.ifsc_code,
                    "account_type": account.account_type,
                    "is_primary": account.is_primary,
                }
                for account in accounts
            ],
        },
        errors=None,
    )


__all__ = ["employee_pii_router", "router"]
