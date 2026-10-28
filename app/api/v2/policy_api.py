"""API v2 router for the AI Policy Explainer and RAG chatbot Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_employee_or_above
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.policy_service import PolicyService

import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/policies",
    tags=["AI Policy Explainer v2"],
    dependencies=[Depends(require_employee_or_above)],
)


# Requests
class UploadPolicyRequest(BaseModel):
    company_id: uuid.UUID
    title: str = Field(..., min_length=2)
    category: str = Field(..., description="LEAVE | TRAVEL | IT | SECURITY | PAYROLL | COMPLIANCE")
    raw_content: str = Field(..., min_length=10)

class ChatPolicyQuery(BaseModel):
    company_id: uuid.UUID
    query: str = Field(..., min_length=2)
    language: Optional[str] = "English"
    model: Optional[str] = None


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Upload policy manual and generate RAG vector chunk mappings",
)
async def upload_policy(
    body: UploadPolicyRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Saves policy text and calculates chunk embeddings using local nomic-embed-text."""
    service = PolicyService(db)
    doc = await service.upload_policy_document(
        company_id=body.company_id,
        title=body.title,
        category=body.category,
        raw_content=body.raw_content
    )
    return APIResponse[dict](
        success=True,
        message="Policy document uploaded and indexed successfully.",
        data={
            "document_id": str(doc.id),
            "title": doc.title,
            "category": doc.category,
        },
        errors=None
    )


@router.post(
    "/chat",
    response_model=APIResponse[dict],
    summary="Query company policies chatbot using vector search context",
)
async def query_chatbot(
    body: ChatPolicyQuery,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Searches vector chunks and runs local LLM to answer policy queries in any language."""
    service = PolicyService(db)
    result = await service.answer_policy_query(
        company_id=body.company_id,
        user_query=body.query,
        language=body.language,
        model=body.model
    )
    return APIResponse[dict](
        success=True,
        message="Policy query answered.",
        data=result,
        errors=None
    )


# ── Policy governance (Batch 5) ──────────────────────────────────────────────
from datetime import date
from fastapi import Header, HTTPException, Request
from sqlalchemy import select
from app.models.employee import Employee
from app.models.employee_policy_acceptance import EmployeePolicyAcceptance
from app.models.policy import CompanyPolicyDocument
from app.services.policy_service import PolicyGovernanceService


def _tenant(claims: dict) -> uuid.UUID:
    value = claims.get("company_id") if claims else None
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required")
    return uuid.UUID(str(value))


def _user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(str(claims["sub"]))


def _role(claims: dict) -> str:
    role = claims.get("role") or claims.get("user_role") or "employee"
    if isinstance(role, dict):
        role = role.get("name", "employee")
    return str(getattr(role, "value", role)).lower()


def _require_policy_admin(claims: dict) -> None:
    if _role(claims) not in {"admin", "hr_admin", "super_admin", "it_admin"}:
        raise HTTPException(status_code=403, detail="Policy administrator access required")


def _policy_dict(doc: CompanyPolicyDocument) -> dict:
    return {
        "id": str(doc.id), "title": doc.title, "category": doc.category,
        "version_number": doc.version_number,
        "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
        "supersedes_policy_id": str(doc.supersedes_policy_id) if doc.supersedes_policy_id else None,
        "status": doc.status, "acknowledgement_required": doc.acknowledgement_required,
        "acknowledgement_due_date": doc.acknowledgement_due_date.isoformat() if doc.acknowledgement_due_date else None,
        "target_branch_ids": doc.target_branch_ids, "target_departments": doc.target_departments,
        "target_roles": doc.target_roles, "target_employment_types": doc.target_employment_types,
    }


class PolicyVersionRequest(BaseModel):
    title: str = Field(min_length=2)
    category: str
    raw_content: str = Field(min_length=10)
    version_number: str = "1.0"
    effective_date: date | None = None
    supersedes_policy_id: uuid.UUID | None = None
    acknowledgement_required: bool = True
    acknowledgement_due_date: date | None = None
    reminder_after_days: int = Field(3, ge=1)
    escalation_after_days: int = Field(7, ge=1)
    target_branch_ids: list[str] = Field(default_factory=list)
    target_departments: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    target_employment_types: list[str] = Field(default_factory=list)


class PolicyAcknowledgeRequest(BaseModel):
    digital_signature: str = Field(min_length=1)
    request_id: str | None = None


@router.post("/documents/versions", status_code=status.HTTP_201_CREATED)
async def create_policy_version(
    body: PolicyVersionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    _require_policy_admin(claims)
    service = PolicyGovernanceService(db)
    try:
        doc = await service.create_version(company_id=_tenant(claims), **body.model_dump())
        return {"success": True, "data": _policy_dict(doc)}
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 404, detail=str(exc)) from exc


@router.post("/documents/{policy_id}/publish")
async def publish_policy(
    policy_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    _require_policy_admin(claims)
    try:
        doc, targeted = await PolicyGovernanceService(db).publish(policy_id, company_id=_tenant(claims))
        return {"success": True, "data": {**_policy_dict(doc), "targeted_employees": targeted}}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/acknowledgements/pending")
async def pending_policy_acknowledgements(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == _user_id(claims), Employee.company_id == _tenant(claims),
    ))).scalar_one_or_none()
    if employee is None:
        return {"success": True, "data": []}
    rows = await PolicyGovernanceService(db).pending(company_id=_tenant(claims), employee_id=employee.id)
    return {"success": True, "data": [{
        "assignment_id": str(assignment.id), "policy_id": str(policy.id),
        "title": policy.title, "version_number": policy.version_number,
        "due_at": assignment.due_at.isoformat(), "reminder_count": assignment.reminder_count,
        "escalated_at": assignment.escalated_at.isoformat() if assignment.escalated_at else None,
    } for assignment, policy in rows]}


@router.post("/documents/{policy_id}/acknowledge")
async def acknowledge_policy(
    policy_id: uuid.UUID, body: PolicyAcknowledgeRequest, request: Request,
    user_agent: Annotated[str | None, Header()] = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == _user_id(claims), Employee.company_id == _tenant(claims),
    ))).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    try:
        acceptance = await PolicyGovernanceService(db).acknowledge(
            policy_id, employee_id=employee.id, user_id=_user_id(claims),
            digital_signature=body.digital_signature,
            ip_address=request.client.host if request.client else None,
            user_agent=user_agent, request_id=body.request_id,
        )
        return {"success": True, "data": PolicyGovernanceService.acknowledgement_proof(acceptance)}
    except (ValueError, LookupError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else (404 if isinstance(exc, LookupError) else 400)
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/acknowledgements/{acceptance_id}/proof")
async def policy_acknowledgement_proof(
    acceptance_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    acceptance = await db.get(EmployeePolicyAcceptance, acceptance_id)
    if acceptance is None:
        raise HTTPException(status_code=404, detail="Acknowledgement not found")
    employee = await db.get(Employee, acceptance.employee_id)
    if employee is None or employee.company_id != _tenant(claims):
        raise HTTPException(status_code=404, detail="Acknowledgement not found")
    if employee.user_id != _user_id(claims):
        _require_policy_admin(claims)
    return {"success": True, "data": PolicyGovernanceService.acknowledgement_proof(acceptance)}


@router.post("/acknowledgements/reminders/run")
async def trigger_policy_reminders(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
):
    _require_policy_admin(claims)
    result = await PolicyGovernanceService(db).trigger_reminders(company_id=_tenant(claims))
    return {"success": True, "data": result}
