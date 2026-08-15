"""API v2 routers for: Org Map, Skill Gap, Shift Planner, Digital Twin."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.auth import APIResponse
from app.services.org_intelligence_services import (
    DigitalTwinService,
    OrgMapService,
    ShiftPlannerService,
    SkillGapService,
)

# ── Org Map ──────────────────────────────────────────────
org_map_router = APIRouter(
    prefix="/org-map",
    tags=["AI Org Intelligence Map v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class OrgMapRequest(BaseModel):
    company_id: uuid.UUID
    company_data: str = Field(..., description="Serialized company structure data")
    model: Optional[str] = None


@org_map_router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Generate AI organization intelligence map",
)
async def generate_org_map(
    body: OrgMapRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    snap = await OrgMapService(db).generate_org_map(body.company_id, body.company_data, body.model)
    return APIResponse[dict](
        success=True,
        message="Org map generated.",
        data={"snapshot_id": str(snap.id), "ai_insights": snap.ai_insights},
        errors=None,
    )


# ── Skill Gap ─────────────────────────────────────────────
skill_gap_router = APIRouter(
    prefix="/skill-gap",
    tags=["AI Skill Gap Analysis v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class SkillGapRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    target_role: str
    current_skills: list[str]
    required_skills: list[str]
    model: Optional[str] = None


@skill_gap_router.post(
    "/analyze",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Analyze skill gap for an employee",
)
async def analyze_skill_gap(
    body: SkillGapRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    rec = await SkillGapService(db).analyze_skill_gap(
        body.company_id,
        body.employee_id,
        body.target_role,
        body.current_skills,
        body.required_skills,
        body.model,
    )
    return APIResponse[dict](
        success=True,
        message="Skill gap analyzed.",
        data={
            "analysis_id": str(rec.id),
            "promotion_readiness_score": rec.promotion_readiness_score,
            "missing_skills": rec.missing_skills,
        },
        errors=None,
    )


# ── Shift Planner ─────────────────────────────────────────
shift_router = APIRouter(
    prefix="/shifts",
    tags=["AI Shift Planner v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class ShiftPlanRequest(BaseModel):
    company_id: uuid.UUID
    department: Optional[str] = None
    plan_type: str = Field("WEEKLY", description="WEEKLY | MONTHLY | ROTATION | HOLIDAY")
    period_start: date
    period_end: date
    employee_ids: list[uuid.UUID]
    constraints: str = "Standard 8-hour shifts, no overtime without approval."
    model: Optional[str] = None


@shift_router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Generate AI-optimized shift plan",
)
async def create_shift_plan(
    body: ShiftPlanRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    plan = await ShiftPlannerService(db).create_shift_plan(
        body.company_id,
        body.department,
        body.plan_type,
        body.period_start,
        body.period_end,
        [str(e) for e in body.employee_ids],
        body.constraints,
        body.model,
    )
    return APIResponse[dict](
        success=True,
        message="Shift plan created.",
        data={
            "plan_id": str(plan.id),
            "entries_count": len(plan.entries),
            "ai_notes": plan.ai_optimization_notes,
        },
        errors=None,
    )


# ── Digital Twin ──────────────────────────────────────────
digital_twin_router = APIRouter(
    prefix="/digital-twin",
    tags=["AI Employee Digital Twin v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class DigitalTwinRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_data: dict[str, Any]
    model: Optional[str] = None


@digital_twin_router.post(
    "/sync",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Sync and forecast employee digital twin",
)
async def sync_digital_twin(
    body: DigitalTwinRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    twin = await DigitalTwinService(db).generate_or_update_twin(
        body.company_id, body.employee_id, body.employee_data, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Digital twin synced.",
        data={
            "twin_id": str(twin.id),
            "performance_score": twin.performance_score,
            "ai_forecast": twin.ai_performance_forecast,
        },
        errors=None,
    )
