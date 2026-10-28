"""Confidential grievance and POSH APIs."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.grievance_posh import POSHEvidence
from app.services.grievance_posh_service import ConfidentialityError, GrievancePOSHService

router = APIRouter(tags=["Grievance & POSH v2"])
Claims = Annotated[dict, Depends(get_current_user_claims)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


def _uid(claims: dict) -> uuid.UUID:
    return uuid.UUID(str(claims["sub"]))


def _company(claims: dict) -> uuid.UUID:
    value = claims.get("company_id")
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required.")
    return uuid.UUID(str(value))


def _role(claims: dict) -> str:
    role = claims.get("role") or claims.get("user_role") or "employee"
    if isinstance(role, dict):
        role = role.get("name", "employee")
    return str(role).lower()


def _admin(claims: dict) -> None:
    if _role(claims) not in {"admin", "hr_admin", "super_admin", "posh_admin", "it_admin"}:
        raise HTTPException(status_code=403, detail="HR/POSH administrator access required.")


def _translate(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ConfidentialityError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _employee_for_user(db: AsyncSession, claims: dict) -> Employee | None:
    return (await db.execute(select(Employee).where(
        Employee.user_id == _uid(claims), Employee.company_id == _company(claims),
    ))).scalar_one_or_none()


class GrievanceCreate(BaseModel):
    category: str = Field(min_length=2, max_length=50)
    subject: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=5)
    anonymous: bool = False
    confidential: bool = True
    sla_hours: int = Field(72, ge=1, le=24 * 90)
    accused_user_ids: list[uuid.UUID] = Field(default_factory=list)
    accused_employee_ids: list[uuid.UUID] = Field(default_factory=list)
    accused_manager_ids: list[uuid.UUID] = Field(default_factory=list)


class InvestigatorAssign(BaseModel):
    investigator_id: uuid.UUID


class ResolutionRequest(BaseModel):
    resolution: str = Field(min_length=2)


class AppealRequest(BaseModel):
    reason: str = Field(min_length=5)
    receipt_token: str | None = None


class AppealDecision(BaseModel):
    decision: str
    resolution: str = Field(min_length=2)


class ICCMemberInput(BaseModel):
    user_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    name: str
    gender: str
    role: str
    is_external: bool = False
    is_active: bool = True
    appointed_at: date | None = None


class ICCCreate(BaseModel):
    name: str
    term_start: date
    term_end: date
    members: list[ICCMemberInput]
    enforce_composition: bool = True


class POSHComplaintCreate(BaseModel):
    committee_id: uuid.UUID
    description: str = Field(min_length=5)
    anonymous: bool = False
    accused_user_ids: list[uuid.UUID] = Field(default_factory=list)


class ConciliationRequest(BaseModel):
    requested: bool
    status: str
    terms: str | None = None
    receipt_token: str | None = None


class RecommendationRequest(BaseModel):
    recommendation: str = Field(min_length=2)


class TrainingRequest(BaseModel):
    audience: str
    training_title: str
    completed_at: datetime
    employee_id: uuid.UUID | None = None
    icc_member_id: uuid.UUID | None = None
    provider: str | None = None
    valid_until: date | None = None
    score: int | None = Field(None, ge=0, le=100)
    certificate_reference: str | None = None


@router.post("/grievances", status_code=status.HTTP_201_CREATED)
async def create_grievance(body: GrievanceCreate, claims: Claims, db: Session) -> dict[str, Any]:
    employee = await _employee_for_user(db, claims)
    service = GrievancePOSHService(db)
    try:
        case = await service.create_grievance(
            company_id=_company(claims), category=body.category, subject=body.subject,
            description=body.description, anonymous=body.anonymous, confidential=body.confidential,
            reporter_employee_id=None if body.anonymous else (employee.id if employee else None),
            reporter_user_id=None if body.anonymous else _uid(claims), sla_hours=body.sla_hours,
            accused_user_ids=body.accused_user_ids, accused_employee_ids=body.accused_employee_ids,
            accused_manager_ids=body.accused_manager_ids, actor_id=_uid(claims),
        )
        data = service.serialize_grievance(case, include_reporter=True)
        data["receipt_token"] = case.receipt_token
        return {"success": True, "data": data, "message": "Confidential grievance filed."}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.get("/grievances/{case_id}")
async def get_grievance(
    case_id: uuid.UUID, claims: Claims, db: Session,
    receipt: Annotated[str | None, Header(alias="X-Grievance-Receipt")] = None,
) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        case = await service.get_grievance(
            case_id, company_id=_company(claims), actor_id=_uid(claims),
            actor_role=_role(claims), receipt_token=receipt,
        )
        include = _role(claims) in {"admin", "hr_admin", "super_admin"} or case.reporter_user_id == _uid(claims)
        return {"success": True, "data": service.serialize_grievance(case, include_reporter=include)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/grievances/{case_id}/investigator")
async def assign_investigator(case_id: uuid.UUID, body: InvestigatorAssign, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    service = GrievancePOSHService(db)
    try:
        case = await service.assign_investigator(
            case_id, company_id=_company(claims), investigator_id=body.investigator_id, actor_id=_uid(claims), actor_role=_role(claims),
        )
        return {"success": True, "data": service.serialize_grievance(case, include_reporter=True)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/grievances/{case_id}/resolve")
async def resolve_grievance(case_id: uuid.UUID, body: ResolutionRequest, claims: Claims, db: Session) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        case = await service.resolve_grievance(
            case_id, company_id=_company(claims), resolution=body.resolution,
            actor_id=_uid(claims), actor_role=_role(claims),
        )
        return {"success": True, "data": service.serialize_grievance(case, include_reporter=True)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/grievances/{case_id}/appeal")
async def appeal_grievance(case_id: uuid.UUID, body: AppealRequest, claims: Claims, db: Session) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        case = await service.appeal_grievance(
            case_id, company_id=_company(claims), reason=body.reason,
            actor_id=_uid(claims), receipt_token=body.receipt_token,
        )
        return {"success": True, "data": service.serialize_grievance(case)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/grievances/{case_id}/appeal/decision")
async def decide_appeal(case_id: uuid.UUID, body: AppealDecision, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    service = GrievancePOSHService(db)
    try:
        case = await service.decide_appeal(
            case_id, company_id=_company(claims), decision=body.decision,
            resolution=body.resolution, actor_id=_uid(claims), actor_role=_role(claims),
        )
        return {"success": True, "data": service.serialize_grievance(case, include_reporter=True)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/grievances/escalations/run")
async def escalate_grievances(claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    count = await GrievancePOSHService(db).escalate_overdue(company_id=_company(claims))
    return {"success": True, "data": {"escalated": count}}


@router.post("/posh/icc", status_code=status.HTTP_201_CREATED)
async def create_icc(body: ICCCreate, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    service = GrievancePOSHService(db)
    try:
        committee = await service.create_icc_committee(
            company_id=_company(claims), name=body.name, term_start=body.term_start,
            term_end=body.term_end, members=[m.model_dump() for m in body.members],
            enforce_composition=body.enforce_composition,
        )
        return {"success": True, "data": {
            "id": str(committee.id), "name": committee.name,
            "composition": service.validate_icc_composition(committee.members),
        }}
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.get("/posh/icc/{committee_id}/composition")
async def icc_composition(committee_id: uuid.UUID, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    service = GrievancePOSHService(db)
    try:
        committee = await service.get_icc_committee(committee_id, company_id=_company(claims))
        return {"success": True, "data": service.validate_icc_composition(committee.members)}
    except LookupError as exc:
        _translate(exc)


@router.post("/posh/complaints", status_code=status.HTTP_201_CREATED)
async def create_posh_complaint(body: POSHComplaintCreate, claims: Claims, db: Session) -> dict[str, Any]:
    employee = await _employee_for_user(db, claims)
    service = GrievancePOSHService(db)
    try:
        complaint = await service.create_posh_complaint(
            company_id=_company(claims), committee_id=body.committee_id, description=body.description,
            anonymous=body.anonymous, accused_user_ids=body.accused_user_ids,
            reporter_employee_id=None if body.anonymous else (employee.id if employee else None),
            reporter_user_id=None if body.anonymous else _uid(claims),
        )
        data = service.serialize_posh(complaint)
        data["receipt_token"] = complaint.receipt_token
        return {"success": True, "data": data}
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.get("/posh/complaints/{complaint_id}")
async def get_posh_complaint(
    complaint_id: uuid.UUID, claims: Claims, db: Session,
    receipt: Annotated[str | None, Header(alias="X-POSH-Receipt")] = None,
) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        complaint = await service.get_posh_complaint(
            complaint_id, company_id=_company(claims), actor_id=_uid(claims),
            actor_role=_role(claims), receipt_token=receipt,
        )
        return {"success": True, "data": service.serialize_posh(complaint)}
    except (LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/posh/complaints/{complaint_id}/conciliation")
async def conciliate_posh(complaint_id: uuid.UUID, body: ConciliationRequest, claims: Claims, db: Session) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        complaint = await service.record_conciliation(
            complaint_id, company_id=_company(claims), actor_id=_uid(claims),
            requested=body.requested, status_value=body.status, terms=body.terms,
            actor_role=_role(claims), receipt_token=body.receipt_token,
        )
        return {"success": True, "data": service.serialize_posh(complaint)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/posh/complaints/{complaint_id}/inquiry/start")
async def start_posh_inquiry(complaint_id: uuid.UUID, claims: Claims, db: Session) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        await service.get_posh_complaint(complaint_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        complaint = await service.start_posh_inquiry(complaint_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        return {"success": True, "data": service.serialize_posh(complaint)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/posh/complaints/{complaint_id}/recommendation")
async def recommend_posh(complaint_id: uuid.UUID, body: RecommendationRequest, claims: Claims, db: Session) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        await service.get_posh_complaint(complaint_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        complaint = await service.complete_posh_inquiry(
            complaint_id, company_id=_company(claims), actor_id=_uid(claims), recommendation=body.recommendation, actor_role=_role(claims),
        )
        return {"success": True, "data": service.serialize_posh(complaint)}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/posh/complaints/{complaint_id}/evidence", status_code=status.HTTP_201_CREATED)
async def upload_posh_evidence(
    complaint_id: uuid.UUID, claims: Claims, db: Session, file: UploadFile = File(...),
) -> dict[str, Any]:
    service = GrievancePOSHService(db)
    try:
        await service.get_posh_complaint(complaint_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Evidence file exceeds the 10 MB limit.")
        evidence = await service.add_evidence(
            complaint_id, company_id=_company(claims), actor_id=_uid(claims),
            file_name=file.filename or "evidence.bin", content_type=file.content_type or "application/octet-stream", content=content, actor_role=_role(claims),
        )
        return {"success": True, "data": {"id": str(evidence.id), "sha256": evidence.sha256, "file_name": evidence.file_name}}
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.get("/posh/evidence/{evidence_id}")
async def download_posh_evidence(evidence_id: uuid.UUID, claims: Claims, db: Session) -> Response:
    service = GrievancePOSHService(db)
    try:
        complaint_id = (await db.execute(
            select(POSHEvidence.complaint_id).where(POSHEvidence.id == evidence_id)
        )).scalar_one_or_none()
        if complaint_id:
            await service.get_posh_complaint(complaint_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        content, evidence = await service.read_evidence(evidence_id, company_id=_company(claims), actor_id=_uid(claims), actor_role=_role(claims))
        return Response(content=content, media_type=evidence.content_type, headers={"Content-Disposition": f'attachment; filename="{evidence.file_name}"'})
    except (ValueError, LookupError, ConfidentialityError) as exc:
        _translate(exc)


@router.post("/posh/training", status_code=status.HTTP_201_CREATED)
async def record_posh_training(body: TrainingRequest, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    try:
        record = await GrievancePOSHService(db).record_training(company_id=_company(claims), **body.model_dump())
        return {"success": True, "data": {"id": str(record.id), "audience": record.audience}}
    except ValueError as exc:
        _translate(exc)


@router.post("/posh/annual-return/{return_year}")
async def generate_posh_annual_return(return_year: int, claims: Claims, db: Session) -> dict[str, Any]:
    _admin(claims)
    annual = await GrievancePOSHService(db).generate_annual_return(
        company_id=_company(claims), return_year=return_year, actor_id=_uid(claims),
    )
    return {"success": True, "data": {"id": str(annual.id), "section_21": annual.section_21, "section_22": annual.section_22}}
