"""Background verification administration, candidate consent, and vendor webhooks."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin, translate, user_id
from app.db.database import get_db_session
from app.services.bgv_service import BGVService, make_consent_token, parse_consent_token

router = APIRouter(prefix="/bgv", tags=["Background Verification v2"])


class VendorRequest(BaseModel):
    name: str
    api_base_url: str
    api_token: str | None = None
    webhook_secret: str = Field(min_length=16)


class CaseRequest(BaseModel):
    vendor_id: uuid.UUID
    candidate_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    check_types: list[str] = Field(default_factory=lambda: ["IDENTITY", "CRIMINAL", "EDUCATION", "EMPLOYMENT"])


class ConsentRequest(BaseModel):
    accepted: bool
    consent_text: str = Field(min_length=20)
    consent_reference: str | None = None


class DiscrepancyResolution(BaseModel):
    resolution: str
    notes: str = Field(min_length=5)


def _case(case) -> dict[str, Any]:
    return {
        "id": str(case.id), "status": case.status, "vendor_reference": case.vendor_reference,
        "consent_at": case.consent_at.isoformat() if case.consent_at else None,
        "consent_text_hash": case.consent_text_hash,
        "checks": [{
            "id": str(check.id), "check_type": check.check_type, "status": check.status,
            "discrepancy_flag": check.discrepancy_flag, "discrepancy_details": check.discrepancy_details,
            "resolution_status": check.resolution_status, "resolution_notes": check.resolution_notes,
            "result": check.result_json,
        } for check in case.checks],
    }


@router.post("/vendors", status_code=201)
async def create_vendor(body: VendorRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        vendor = await BGVService(db).create_vendor(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(vendor.id), "name": vendor.name, "is_active": vendor.is_active}, "BGV vendor configured")
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/cases", status_code=201)
async def create_case(body: CaseRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        case = await BGVService(db).create_case(
            company_id=company_id(claims), actor_id=user_id(claims), **body.model_dump(),
        )
        return ok({**_case(case), "consent_token": make_consent_token(case)}, "BGV case created; send the consent link to the candidate")
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/public/consent/{token}")
async def capture_public_consent(token: str, body: ConsentRequest, request: Request, db: AsyncSession = Depends(get_db_session)):
    try:
        case_id, tenant_id = parse_consent_token(token)
        case = await BGVService(db).capture_consent(
            case_id, company_id=tenant_id, accepted=body.accepted, consent_text=body.consent_text,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"), consent_reference=body.consent_reference,
        )
        return ok({"case_id": str(case.id), "status": case.status, "consent_at": case.consent_at.isoformat()}, "Digital consent captured")
    except (ValueError, LookupError, PermissionError) as exc:
        translate(exc)


@router.post("/cases/{case_id}/submit")
async def submit_case(case_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        case = await BGVService(db).submit_case(case_id, company_id=company_id(claims))
        return ok(_case(case), "BGV case submitted to vendor")
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/cases/{case_id}")
async def get_case(case_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        case = await BGVService(db)._case(case_id, company_id(claims))
        return ok(_case(case))
    except LookupError as exc:
        translate(exc)


@router.post("/checks/{check_id}/discrepancy")
async def resolve_discrepancy(check_id: uuid.UUID, body: DiscrepancyResolution, claims: Claims, db: Session):
    require_admin(claims)
    try:
        check = await BGVService(db).resolve_discrepancy(
            check_id, company_id=company_id(claims), actor_id=user_id(claims),
            resolution=body.resolution, notes=body.notes,
        )
        return ok({"id": str(check.id), "resolution_status": check.resolution_status, "resolved_at": check.resolved_at.isoformat()})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/webhooks/{tenant_id}/{vendor_id}")
async def bgv_webhook(
    tenant_id: uuid.UUID, vendor_id: uuid.UUID, request: Request,
    signature: Annotated[str | None, Header(alias="X-BGV-Signature")] = None,
    db: AsyncSession = Depends(get_db_session),
):
    try:
        result = await BGVService(db).handle_webhook(
            company_id=tenant_id, vendor_id=vendor_id,
            raw_body=await request.body(), signature=signature,
        )
        return ok(result, "BGV webhook processed")
    except (ValueError, LookupError, PermissionError) as exc:
        translate(exc)
