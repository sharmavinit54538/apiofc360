"""API v2 routers for: Workforce Forecasting, Talent Marketplace, Meeting Intelligence, Compliance Monitor, Employee Risk Engine, Executive Copilot."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager, require_executive
from app.db.database import get_db_session
from app.schemas.auth import APIResponse
from app.services.enterprise_intelligence_services import (
    ComplianceMonitorService,
    EmployeeRiskService,
    ExecutiveCopilotService,
    MeetingIntelligenceService,
    TalentMarketplaceService,
    WorkforceForecastService,
    WorkforcePlanningService,
)

# ── Workforce Forecasting ─────────────────────────────────
workforce_router = APIRouter(
    prefix="/workforce",
    tags=["AI Workforce Forecasting v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class WorkforceForecastRequest(BaseModel):
    company_id: uuid.UUID
    forecast_period: str = Field(..., example="Q3 2026")
    company_snapshot: dict[str, Any] = {}
    model: Optional[str] = None


@workforce_router.post(
    "/forecast",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Run AI workforce forecasting run",
)
async def run_workforce_forecast(
    body: WorkforceForecastRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    run = await WorkforceForecastService(db).run_forecast(
        body.company_id, body.forecast_period, body.company_snapshot, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Workforce forecast completed.",
        data={
            "run_id": str(run.id),
            "predicted_hiring_needs": run.predicted_hiring_needs,
            "predicted_attrition_count": run.predicted_attrition_count,
            "workforce_plan_narrative": run.workforce_plan_narrative,
        },
        errors=None,
    )


class WorkforcePlanRequest(BaseModel):
    fiscal_year: str = Field(..., pattern=r"^\d{4}-\d{4}$", examples=["2026-2027"])
    department: str = Field(..., min_length=1, max_length=100)
    approved_headcount: int = Field(..., ge=0)
    annual_hiring_budget_paise: int = Field(..., ge=0)


@workforce_router.put("/plans", response_model=APIResponse[dict])
async def upsert_workforce_plan(
    body: WorkforcePlanRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    from app.api.v2.enterprise_dependencies import company_id
    try:
        plan = await WorkforcePlanningService(db).upsert_plan(
            company_id=company_id(claims), **body.model_dump(),
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Workforce plan approved.", data={
        "id": str(plan.id), "fiscal_year": plan.fiscal_year,
        "department": plan.department, "approved_headcount": plan.approved_headcount,
        "annual_hiring_budget_paise": plan.annual_hiring_budget_paise,
    }, errors=None)


@workforce_router.get("/planning", response_model=APIResponse[dict])
async def get_workforce_planning(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    fiscal_year: str | None = None,
):
    from app.api.v2.enterprise_dependencies import company_id
    from fastapi import HTTPException
    if fiscal_year is None:
        today = datetime.now().date()
        start = today.year if today.month >= 4 else today.year - 1
        fiscal_year = f"{start}-{start + 1}"
    import re
    if not re.fullmatch(r"\d{4}-\d{4}", fiscal_year):
        raise HTTPException(status_code=422, detail="fiscal_year must be YYYY-YYYY.")
    try:
        data = await WorkforcePlanningService(db).planning(
            company_id=company_id(claims), fiscal_year=fiscal_year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Workforce planning retrieved.", data=data, errors=None)


# ── Talent Marketplace ────────────────────────────────────
talent_router = APIRouter(
    prefix="/talent",
    tags=["AI Talent Marketplace v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class TalentMatchRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_profile: dict[str, Any]
    opportunities: list[str]
    model: Optional[str] = None


@talent_router.post(
    "/match",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Match employee to internal opportunities",
)
async def find_talent_matches(
    body: TalentMatchRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    matches = await TalentMarketplaceService(db).find_matches(
        body.company_id, body.employee_id, body.employee_profile, body.opportunities, body.model
    )
    return APIResponse[dict](
        success=True,
        message=f"{len(matches)} talent matches found.",
        data={
            "match_count": len(matches),
            "matches": [
                {
                    "match_id": str(m.id),
                    "match_type": m.match_type,
                    "match_title": m.match_title,
                    "match_score": str(m.match_score),
                }
                for m in matches
            ],
        },
        errors=None,
    )


# ── Meeting Intelligence ──────────────────────────────────
meetings_router = APIRouter(
    prefix="/meetings",
    tags=["AI Meeting Intelligence v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class MeetingAnalyzeRequest(BaseModel):
    company_id: uuid.UUID
    meeting_title: str
    transcript: str
    model: Optional[str] = None


@meetings_router.post(
    "/analyze",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Analyze meeting transcript and extract MOM, actions, decisions",
)
async def analyze_meeting(
    body: MeetingAnalyzeRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    log = await MeetingIntelligenceService(db).analyze_meeting(
        body.company_id, body.meeting_title, body.transcript, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Meeting analyzed.",
        data={
            "log_id": str(log.id),
            "summary": log.summary,
            "action_items": log.action_items,
            "decisions": log.decisions,
            "mom": log.mom,
        },
        errors=None,
    )


# ── Compliance Monitor ────────────────────────────────────
compliance_router = APIRouter(
    prefix="/compliance",
    tags=["AI Compliance Monitor v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class ComplianceAuditRequest(BaseModel):
    company_id: uuid.UUID
    audit_scope: str = Field(..., description="HR_POLICY | ATTENDANCE | PAYROLL | LABOR_LAW | DATA_PRIVACY")
    data_snapshot: dict[str, Any] = {}
    model: Optional[str] = None


@compliance_router.post(
    "/audit",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Run AI compliance audit",
)
async def run_compliance_audit(
    body: ComplianceAuditRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    log = await ComplianceMonitorService(db).run_audit(
        body.company_id, body.audit_scope, body.data_snapshot, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Compliance audit completed.",
        data={
            "log_id": str(log.id),
            "risk_level": log.risk_level,
            "findings": log.findings,
            "recommendations": log.recommendations,
        },
        errors=None,
    )


# ── Employee Risk Engine ──────────────────────────────────
risk_router = APIRouter(
    prefix="/risk",
    tags=["AI Employee Risk Engine v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class EmployeeRiskRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_profile: dict[str, Any]
    model: Optional[str] = None


@risk_router.post(
    "/assess",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Compute AI employee risk profile",
)
async def assess_employee_risk(
    body: EmployeeRiskRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    assessment = await EmployeeRiskService(db).assess_risk(
        body.company_id, body.employee_id, body.employee_profile, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Employee risk assessed.",
        data={
            "assessment_id": str(assessment.id),
            "overall_risk_level": assessment.overall_risk_level,
            "resignation_risk_score": assessment.resignation_risk_score,
            "burnout_risk_score": assessment.burnout_risk_score,
            "risk_narrative": assessment.risk_narrative,
        },
        errors=None,
    )


# ── Executive Copilot ─────────────────────────────────────
copilot_router = APIRouter(
    prefix="/copilot",
    tags=["AI Executive Copilot v2"],
    dependencies=[Depends(require_admin_or_manager)],
)


class CopilotQueryRequest(BaseModel):
    company_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    query: str = Field(..., min_length=5)
    context: dict[str, Any] = {}
    model: Optional[str] = None


@copilot_router.post(
    "/query",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Ask strategic HR questions to Executive AI Copilot",
)
async def ask_copilot(
    body: CopilotQueryRequest,
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    log = await ExecutiveCopilotService(db).answer_query(
        body.company_id, body.user_id, body.query, body.context, body.model
    )
    return APIResponse[dict](
        success=True,
        message="Executive query answered.",
        data={
            "log_id": str(log.id),
            "query": log.query_text,
            "ai_response": log.ai_response,
        },
        errors=None,
    )


# ---------------------------------------------------------------------------
# Batch 6: Internal Job Board (#27)
# ---------------------------------------------------------------------------
from app.api.v2.enterprise_dependencies import (
    company_id as _tenant_id, ok as _ok, require_admin as _require_admin,
    role as _claims_role, translate as _translate, user_id as _actor_id,
)
from app.middleware.auth import get_current_user_claims
from app.db.database import get_db_session
from app.services.internal_job_service import InternalJobService

ijp_router = APIRouter(prefix="/internal-jobs", tags=["Internal Job Board v2"])


class InternalOpeningRequest(BaseModel):
    title: str
    department: str
    designation: str
    description: str
    min_tenure_months: int = Field(0, ge=0)
    min_performance_score: float | None = Field(None, ge=0, le=5)
    closes_at: Optional[datetime] = None


class InternalApplicationRequest(BaseModel):
    cover_note: str | None = None


class InternalManagerDecision(BaseModel):
    approved: bool
    reason: str | None = None


async def _current_employee(db: AsyncSession, claims: dict):
    from sqlalchemy import select
    from app.models.employee import Employee
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == _actor_id(claims), Employee.company_id == _tenant_id(claims),
        Employee.is_deleted.is_(False),
    ))).scalar_one_or_none()
    if employee is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Employee profile not found for current user.")
    return employee


@ijp_router.post("/openings", status_code=201)
async def create_internal_opening(body: InternalOpeningRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        opening = await InternalJobService(db).create_opening(
            company_id=_tenant_id(claims), created_by=_actor_id(claims), **body.model_dump(),
        )
        return _ok({"id": str(opening.id), "status": opening.status})
    except ValueError as exc:
        _translate(exc)


@ijp_router.get("/openings")
async def list_internal_openings(claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    from sqlalchemy import select
    from app.models.talent_marketplace import InternalJobOpening
    rows = (await db.execute(select(InternalJobOpening).where(
        InternalJobOpening.company_id == _tenant_id(claims), InternalJobOpening.status == "OPEN",
    ))).scalars().all()
    return _ok([{"id": str(row.id), "title": row.title, "department": row.department,
                 "min_tenure_months": row.min_tenure_months,
                 "min_performance_score": float(row.min_performance_score) if row.min_performance_score is not None else None} for row in rows])


@ijp_router.get("/openings/{opening_id}/eligibility")
async def internal_job_eligibility(opening_id: uuid.UUID, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    employee = await _current_employee(db, claims)
    try:
        return _ok(await InternalJobService(db).check_eligibility(opening_id, company_id=_tenant_id(claims), employee_id=employee.id))
    except (ValueError, LookupError) as exc:
        _translate(exc)


@ijp_router.post("/openings/{opening_id}/applications", status_code=201)
async def apply_internal_job(opening_id: uuid.UUID, body: InternalApplicationRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    employee = await _current_employee(db, claims)
    try:
        application = await InternalJobService(db).apply(
            opening_id, company_id=_tenant_id(claims), employee_id=employee.id, cover_note=body.cover_note,
        )
        return _ok({"id": str(application.id), "status": application.status, "eligibility": application.eligibility_json})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@ijp_router.post("/applications/{application_id}/manager-decision")
async def decide_internal_application(application_id: uuid.UUID, body: InternalManagerDecision, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    try:
        application = await InternalJobService(db).manager_decision(
            application_id, company_id=_tenant_id(claims), actor_user_id=_actor_id(claims),
            actor_role=_claims_role(claims), **body.model_dump(),
        )
        return _ok({"id": str(application.id), "status": application.status})
    except (ValueError, LookupError, PermissionError) as exc:
        _translate(exc)
