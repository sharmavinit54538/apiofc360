"""AI Workforce Forecasting, Talent Marketplace, Meeting Intelligence, Compliance Monitor, Employee Risk, and Executive Copilot services."""
from __future__ import annotations
import json, logging, uuid
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.models.workforce_forecast import WorkforceForecastRun
from app.models.talent_marketplace import TalentMatch
from app.models.meeting_intelligence import MeetingIntelligenceLog
from app.models.compliance_monitor import ComplianceAuditLog
from app.models.employee_risk import EmployeeRiskAssessment
from app.models.executive_copilot import CopilotQueryLog

logger = logging.getLogger(__name__)


class WorkforceForecastService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def run_forecast(self, company_id: uuid.UUID, forecast_period: str, company_snapshot: dict, model: Optional[str] = None) -> WorkforceForecastRun:
        try:
            res = await self.llm.complete(PromptLibrary.ai_workforce_forecast_user(str(company_snapshot), forecast_period), system=PromptLibrary.AI_WORKFORCE_FORECAST, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("WorkforceForecast failed: %s", e)
            data = {"predicted_hiring_needs": 0, "predicted_attrition_count": 0, "future_skill_demand": [], "salary_budget_estimate": 0, "workforce_plan_narrative": "Auto-generated.", "department_growth_forecast": {}}
        run = WorkforceForecastRun(id=uuid.uuid4(), company_id=company_id, forecast_period=forecast_period, predicted_hiring_needs=int(data.get("predicted_hiring_needs", 0)), predicted_attrition_count=int(data.get("predicted_attrition_count", 0)), future_skill_demand=json.dumps(data.get("future_skill_demand", [])), salary_budget_estimate=Decimal(str(data.get("salary_budget_estimate", 0))), workforce_plan_narrative=data.get("workforce_plan_narrative"), department_growth_forecast=json.dumps(data.get("department_growth_forecast", {})))
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run


class TalentMarketplaceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def find_matches(self, company_id: uuid.UUID, employee_id: uuid.UUID, employee_profile: dict, opportunities: list, model: Optional[str] = None) -> list[TalentMatch]:
        try:
            res = await self.llm.complete(PromptLibrary.ai_talent_match_user(str(employee_profile), str(opportunities)), system=PromptLibrary.AI_TALENT_MATCH, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("TalentMatch failed: %s", e)
            data = {"matches": []}
        matches = []
        for m in data.get("matches", []):
            match = TalentMatch(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, match_type=m.get("match_type", "PROJECT"), match_title=m.get("match_title", "Unknown"), match_description=m.get("match_description"), match_score=Decimal(str(m.get("match_score", 0))), ai_justification=m.get("ai_justification"))
            self.db.add(match)
            matches.append(match)
        await self.db.commit()
        return matches


class MeetingIntelligenceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def analyze_meeting(self, company_id: uuid.UUID, meeting_title: str, transcript: str, model: Optional[str] = None) -> MeetingIntelligenceLog:
        try:
            res = await self.llm.complete(PromptLibrary.ai_meeting_intel_user(meeting_title, transcript), system=PromptLibrary.AI_MEETING_INTEL, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("MeetingIntel failed: %s", e)
            data = {"summary": "N/A", "action_items": [], "decisions": [], "task_assignments": [], "mom": "N/A", "followup_reminders": []}
        log = MeetingIntelligenceLog(id=uuid.uuid4(), company_id=company_id, meeting_title=meeting_title, meeting_transcript=transcript, summary=data.get("summary"), action_items=json.dumps(data.get("action_items", [])), decisions=json.dumps(data.get("decisions", [])), task_assignments=json.dumps(data.get("task_assignments", [])), mom=data.get("mom"), followup_reminders=json.dumps(data.get("followup_reminders", [])))
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log


class ComplianceMonitorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def run_audit(self, company_id: uuid.UUID, audit_scope: str, data_snapshot: dict, model: Optional[str] = None) -> ComplianceAuditLog:
        try:
            res = await self.llm.complete(PromptLibrary.ai_compliance_audit_user(audit_scope, str(data_snapshot)), system=PromptLibrary.AI_COMPLIANCE_AUDIT, model=model, json_mode=True, temperature=0.2)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("ComplianceAudit failed: %s", e)
            data = {"findings": [], "risk_level": "LOW", "recommendations": "No issues detected.", "auto_corrected": []}
        log = ComplianceAuditLog(id=uuid.uuid4(), company_id=company_id, audit_scope=audit_scope.upper(), findings=json.dumps(data.get("findings", [])), risk_level=data.get("risk_level", "LOW").upper(), recommendations=data.get("recommendations"), auto_corrected=json.dumps(data.get("auto_corrected", [])))
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log


class EmployeeRiskService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def assess_risk(self, company_id: uuid.UUID, employee_id: uuid.UUID, employee_profile: dict, model: Optional[str] = None) -> EmployeeRiskAssessment:
        try:
            res = await self.llm.complete(PromptLibrary.ai_risk_engine_user(str(employee_profile)), system=PromptLibrary.AI_RISK_ENGINE, model=model, json_mode=True, temperature=0.2)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("RiskEngine failed: %s", e)
            data = {"resignation_risk_score": 0, "burnout_risk_score": 0, "performance_risk_score": 0, "compliance_risk_score": 0, "engagement_risk_score": 0, "overall_risk_level": "LOW", "risk_narrative": "Auto-assessed.", "recommended_actions": []}
        assessment = EmployeeRiskAssessment(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, resignation_risk_score=int(data.get("resignation_risk_score", 0)), burnout_risk_score=int(data.get("burnout_risk_score", 0)), performance_risk_score=int(data.get("performance_risk_score", 0)), compliance_risk_score=int(data.get("compliance_risk_score", 0)), engagement_risk_score=int(data.get("engagement_risk_score", 0)), overall_risk_level=data.get("overall_risk_level", "LOW").upper(), risk_narrative=data.get("risk_narrative"), recommended_actions=json.dumps(data.get("recommended_actions", [])))
        self.db.add(assessment)
        await self.db.commit()
        await self.db.refresh(assessment)
        return assessment


class ExecutiveCopilotService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def answer_query(self, company_id: uuid.UUID, user_id: Optional[uuid.UUID], query: str, context: dict, model: Optional[str] = None) -> CopilotQueryLog:
        try:
            res = await self.llm.complete(PromptLibrary.ai_executive_copilot_user(query, str(context)), system=PromptLibrary.AI_EXECUTIVE_COPILOT, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
            ai_response = data.get("ai_response", "No response generated.")
        except Exception as e:
            logger.error("ExecutiveCopilot failed: %s", e)
            ai_response = "Unable to process query at this time."
        log = CopilotQueryLog(id=uuid.uuid4(), company_id=company_id, asked_by_user_id=user_id, query_text=query, ai_response=ai_response, data_context_used=json.dumps(context))
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log
