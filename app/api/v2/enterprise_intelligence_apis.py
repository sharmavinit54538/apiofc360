"""API v2 routers for: Workforce Forecasting, Talent Marketplace, Meeting Intelligence, Compliance Monitor, Employee Risk Engine, Executive Copilot."""
from __future__ import annotations
import uuid
from typing import Annotated, Any, Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.enterprise_intelligence_services import (
    WorkforceForecastService, TalentMarketplaceService, MeetingIntelligenceService,
    ComplianceMonitorService, EmployeeRiskService, ExecutiveCopilotService
)

# ── Workforce Forecasting ─────────────────────────────────
workforce_router = APIRouter(prefix="/workforce", tags=["AI Workforce Forecasting v2"])

class WorkforceForecastRequest(BaseModel):
    company_id: uuid.UUID
    forecast_period: str = Field(..., example="Q3 2026")
    company_snapshot: dict[str, Any] = {}
    model: Optional[str] = None

@workforce_router.post("/forecast", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Run AI workforce forecasting run")
async def run_workforce_forecast(body: WorkforceForecastRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    run = await WorkforceForecastService(db).run_forecast(body.company_id, body.forecast_period, body.company_snapshot, body.model)
    return APIResponse[dict](success=True, message="Workforce forecast completed.", data={"run_id": str(run.id), "predicted_hiring_needs": run.predicted_hiring_needs, "predicted_attrition_count": run.predicted_attrition_count, "workforce_plan_narrative": run.workforce_plan_narrative}, errors=None)

# ── Talent Marketplace ────────────────────────────────────
talent_router = APIRouter(prefix="/talent", tags=["AI Talent Marketplace v2"])

class TalentMatchRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_profile: dict[str, Any]
    opportunities: list[str]
    model: Optional[str] = None

@talent_router.post("/match", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Match employee to internal opportunities")
async def find_talent_matches(body: TalentMatchRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    matches = await TalentMarketplaceService(db).find_matches(body.company_id, body.employee_id, body.employee_profile, body.opportunities, body.model)
    return APIResponse[dict](success=True, message=f"{len(matches)} talent matches found.", data={"match_count": len(matches), "matches": [{"match_id": str(m.id), "match_type": m.match_type, "match_title": m.match_title, "match_score": str(m.match_score)} for m in matches]}, errors=None)

# ── Meeting Intelligence ──────────────────────────────────
meetings_router = APIRouter(prefix="/meetings", tags=["AI Meeting Intelligence v2"])

class MeetingAnalyzeRequest(BaseModel):
    company_id: uuid.UUID
    meeting_title: str
    transcript: str
    model: Optional[str] = None

@meetings_router.post("/analyze", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Analyze meeting transcript and extract MOM, actions, decisions")
async def analyze_meeting(body: MeetingAnalyzeRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    log = await MeetingIntelligenceService(db).analyze_meeting(body.company_id, body.meeting_title, body.transcript, body.model)
    return APIResponse[dict](success=True, message="Meeting analyzed.", data={"log_id": str(log.id), "summary": log.summary, "action_items": log.action_items, "decisions": log.decisions, "mom": log.mom}, errors=None)

# ── Compliance Monitor ────────────────────────────────────
compliance_router = APIRouter(prefix="/compliance", tags=["AI Compliance Monitor v2"])

class ComplianceAuditRequest(BaseModel):
    company_id: uuid.UUID
    audit_scope: str = Field(..., description="HR_POLICY | ATTENDANCE | PAYROLL | LABOR_LAW | DATA_PRIVACY")
    data_snapshot: dict[str, Any] = {}
    model: Optional[str] = None

@compliance_router.post("/audit", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Run AI compliance audit")
async def run_compliance_audit(body: ComplianceAuditRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    log = await ComplianceMonitorService(db).run_audit(body.company_id, body.audit_scope, body.data_snapshot, body.model)
    return APIResponse[dict](success=True, message="Compliance audit completed.", data={"log_id": str(log.id), "risk_level": log.risk_level, "findings": log.findings, "recommendations": log.recommendations}, errors=None)

# ── Employee Risk Engine ──────────────────────────────────
risk_router = APIRouter(prefix="/risk", tags=["AI Employee Risk Engine v2"])

class EmployeeRiskRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_profile: dict[str, Any]
    model: Optional[str] = None

@risk_router.post("/assess", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Compute AI employee risk profile")
async def assess_employee_risk(body: EmployeeRiskRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    assessment = await EmployeeRiskService(db).assess_risk(body.company_id, body.employee_id, body.employee_profile, body.model)
    return APIResponse[dict](success=True, message="Employee risk assessed.", data={"assessment_id": str(assessment.id), "overall_risk_level": assessment.overall_risk_level, "resignation_risk_score": assessment.resignation_risk_score, "burnout_risk_score": assessment.burnout_risk_score, "risk_narrative": assessment.risk_narrative}, errors=None)

# ── Executive Copilot ─────────────────────────────────────
copilot_router = APIRouter(prefix="/copilot", tags=["AI Executive Copilot v2"])

class CopilotQueryRequest(BaseModel):
    company_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    query: str = Field(..., min_length=5)
    context: dict[str, Any] = {}
    model: Optional[str] = None

@copilot_router.post("/query", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Ask strategic HR questions to Executive AI Copilot")
async def ask_copilot(body: CopilotQueryRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    log = await ExecutiveCopilotService(db).answer_query(body.company_id, body.user_id, body.query, body.context, body.model)
    return APIResponse[dict](success=True, message="Executive query answered.", data={"log_id": str(log.id), "query": log.query_text, "ai_response": log.ai_response}, errors=None)
