"""Succession critical roles, successor slates, development, and risk map APIs."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin, require_manager, translate
from app.services.succession_service import SuccessionService

router = APIRouter(prefix="/succession", tags=["Succession Planning v2"])


class RoleRequest(BaseModel):
    title: str
    department: str
    incumbent_employee_id: uuid.UUID | None = None
    vacancy_risk_score: float = Field(50, ge=0, le=100)
    business_impact_score: float = Field(50, ge=0, le=100)


class SuccessorRequest(BaseModel):
    employee_id: uuid.UUID
    performance_score: float = Field(ge=0, le=100)
    potential_score: float = Field(ge=0, le=100)
    skill_coverage_score: float = Field(ge=0, le=100)
    notes: str | None = None


class DevelopmentRequest(BaseModel):
    title: str
    description: str | None = None
    owner_employee_id: uuid.UUID | None = None
    due_date: date


class DevelopmentProgress(BaseModel):
    progress_percentage: int = Field(ge=0, le=100)
    evidence_reference: str | None = None


@router.post("/roles", status_code=201)
async def create_role(body: RoleRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        role = await SuccessionService(db).create_critical_role(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(role.id), "risk_level": role.risk_level}, "Critical role created")
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/roles/{role_id}/successors", status_code=201)
async def add_successor(role_id: uuid.UUID, body: SuccessorRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        slate = await SuccessionService(db).add_successor(role_id, company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(slate.id), "readiness_score": float(slate.readiness_score), "readiness_category": slate.readiness_category})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/slates/{slate_id}/development-actions", status_code=201)
async def add_development_action(slate_id: uuid.UUID, body: DevelopmentRequest, claims: Claims, db: Session):
    require_manager(claims)
    try:
        action = await SuccessionService(db).add_development_action(slate_id, company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(action.id), "status": action.status})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.patch("/development-actions/{action_id}")
async def update_development_action(action_id: uuid.UUID, body: DevelopmentProgress, claims: Claims, db: Session):
    require_manager(claims)
    try:
        action = await SuccessionService(db).update_development_action(action_id, company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(action.id), "status": action.status, "progress_percentage": action.progress_percentage})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/risk-map")
async def leadership_risk_map(claims: Claims, db: Session):
    require_manager(claims)
    return ok(await SuccessionService(db).leadership_risk_map(company_id=company_id(claims)))
