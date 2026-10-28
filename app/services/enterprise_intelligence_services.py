"""AI Workforce Forecasting, Talent Marketplace, Meeting Intelligence, Compliance Monitor, Employee Risk, and Executive Copilot services."""
from __future__ import annotations
import json, logging, uuid
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy import select
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


class WorkforcePlanningService:
    """Approved headcount, requisition cost and monthly hiring-budget burn."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_plan(
        self, *, company_id: uuid.UUID, fiscal_year: str, department: str,
        approved_headcount: int, annual_hiring_budget_paise: int,
    ) -> WorkforcePlan:
        from app.models.workforce_forecast import WorkforcePlan
        if approved_headcount < 0 or annual_hiring_budget_paise < 0:
            raise ValueError("Headcount and hiring budget cannot be negative.")
        department = department.strip()
        if not department:
            raise ValueError("Department is required.")
        plan = (await self.db.execute(select(WorkforcePlan).where(
            WorkforcePlan.company_id == company_id,
            WorkforcePlan.fiscal_year == fiscal_year,
            WorkforcePlan.department == department,
        ))).scalar_one_or_none()
        if plan is None:
            plan = WorkforcePlan(
                id=uuid.uuid4(), company_id=company_id, fiscal_year=fiscal_year,
                department=department, status="APPROVED",
            )
            self.db.add(plan)
        plan.approved_headcount = int(approved_headcount)
        plan.annual_hiring_budget_paise = int(annual_hiring_budget_paise)
        plan.status = "APPROVED"
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def planning(self, *, company_id: uuid.UUID, fiscal_year: str) -> dict[str, Any]:
        from app.models.department import Department
        from app.models.employee import Employee
        from app.models.recruitment import Job
        from app.models.workforce_forecast import WorkforcePlan

        plans = (await self.db.execute(select(WorkforcePlan).where(
            WorkforcePlan.company_id == company_id, WorkforcePlan.fiscal_year == fiscal_year,
            WorkforcePlan.status == "APPROVED",
        ))).scalars().all()
        departments = (await self.db.execute(select(Department).where(
            Department.company_id == company_id, Department.is_deleted.is_(False),
        ))).scalars().all()
        employees = (await self.db.execute(select(Employee).where(
            Employee.company_id == company_id, Employee.status == "ACTIVE",
            Employee.is_deleted.is_(False),
        ))).scalars().all()
        jobs = (await self.db.execute(select(Job).where(
            Job.company_id == company_id, Job.is_deleted.is_(False),
            Job.status.in_(("OPEN", "APPROVED", "PUBLISHED")),
        ))).scalars().all()

        plan_by_department = {plan.department: plan for plan in plans}
        department_by_name = {department.department_name: department for department in departments}
        names = set(plan_by_department) | set(department_by_name)
        names |= {employee.department or "UNASSIGNED" for employee in employees}
        names |= {job.department or "UNASSIGNED" for job in jobs}
        headcount_rows = []
        burn_rows = []
        requisition_rows = []
        total_projected = 0
        for name in sorted(names):
            actual = sum((employee.department or "UNASSIGNED") == name for employee in employees)
            plan = plan_by_department.get(name)
            department = department_by_name.get(name)
            approved = plan.approved_headcount if plan else int(department.employee_capacity or actual) if department else actual
            annual_budget = int(plan.annual_hiring_budget_paise) if plan else int(Decimal(str(department.budget or 0)) * 100) if department else 0
            source = "APPROVED_WORKFORCE_PLAN" if plan else "DEPARTMENT_FALLBACK" if department else "ACTUAL_HEADCOUNT_FALLBACK"
            headcount_rows.append({
                "department": name, "approved_headcount": approved,
                "actual_headcount": actual, "headcount_gap": approved - actual,
                "utilization_pct": round(actual * 100 / approved, 2) if approved else None,
                "source": source,
            })
            department_jobs = [job for job in jobs if (job.department or "UNASSIGNED") == name]
            projected = 0
            for job in department_jobs:
                low = Decimal(str(job.min_salary or 0))
                high = Decimal(str(job.max_salary or 0))
                if low and high and high < low:
                    raise ValueError(f"Job '{job.title}' has an invalid salary range.")
                midpoint = (low + high) / 2 if low or high else Decimal("0")
                cost = int(midpoint * max(1, int(job.vacancies or 1)) * 100)
                projected += cost
                requisition_rows.append({
                    "job_id": str(job.id), "requisition_type": "JOB",
                    "title": job.title, "department": name,
                    "vacancies": max(1, int(job.vacancies or 1)),
                    "annual_cost_projection_paise": cost,
                    "salary_data_available": bool(low or high),
                })
            total_projected += projected
            monthly_projection = int(Decimal(projected) / 12)
            monthly_budget = int(Decimal(annual_budget) / 12)
            burn_rows.append({
                "department": name, "annual_hiring_budget_paise": annual_budget,
                "monthly_hiring_budget_paise": monthly_budget,
                "annual_requisition_projection_paise": projected,
                "monthly_requisition_projection_paise": monthly_projection,
                "monthly_burn_rate_pct": round(monthly_projection * 100 / monthly_budget, 2) if monthly_budget else None,
                "annual_budget_utilization_pct": round(projected * 100 / annual_budget, 2) if annual_budget else None,
                "budget_status": "UNBUDGETED" if not annual_budget and projected else "OVER_BUDGET" if projected > annual_budget else "WITHIN_BUDGET",
            })
        return {
            "company_id": str(company_id), "fiscal_year": fiscal_year,
            "approved_vs_actual": headcount_rows,
            "requisitions": requisition_rows,
            "total_requisition_cost_projection_paise": total_projected,
            "monthly_hiring_budget_burn": burn_rows,
            "total_approved_headcount": sum(row["approved_headcount"] for row in headcount_rows),
            "total_actual_headcount": sum(row["actual_headcount"] for row in headcount_rows),
            "salary_projections_are_estimates": True,
        }


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
