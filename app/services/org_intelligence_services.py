"""AI Organization Intelligence Map, Skill Gap Analysis, Shift Planner, and Digital Twin services."""
from __future__ import annotations
import json, logging, uuid
from datetime import date
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.models.org_map import OrgHierarchySnapshot
from app.models.skill_gap import SkillGapAnalysis
from app.models.shift_plan import ShiftPlan, ShiftPlanEntry
from app.models.digital_twin import EmployeeDigitalTwin

logger = logging.getLogger(__name__)

class OrgMapService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def generate_org_map(self, company_id: uuid.UUID, company_data: str, model: Optional[str] = None) -> OrgHierarchySnapshot:
        try:
            res = await self.llm.complete(PromptLibrary.ai_org_map_user(company_data), system=PromptLibrary.AI_ORG_MAP_GEN, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("OrgMap generation failed: %s", e)
            data = {"hierarchy_json": "{}", "department_structure": "{}", "leadership_map": "{}", "ai_insights": "Auto-generated fallback."}
        snap = OrgHierarchySnapshot(id=uuid.uuid4(), company_id=company_id, hierarchy_json=data.get("hierarchy_json", "{}"), department_structure=data.get("department_structure", "{}"), leadership_map=data.get("leadership_map", "{}"), ai_insights=data.get("ai_insights"))
        self.db.add(snap)
        await self.db.commit()
        await self.db.refresh(snap)
        return snap


class SkillGapService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def analyze_skill_gap(self, company_id: uuid.UUID, employee_id: uuid.UUID, target_role: str, current_skills: list, required_skills: list, model: Optional[str] = None) -> SkillGapAnalysis:
        try:
            res = await self.llm.complete(PromptLibrary.ai_skill_gap_user(str(current_skills), target_role, str(required_skills)), system=PromptLibrary.AI_SKILL_GAP, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("SkillGap analysis failed: %s", e)
            data = {"missing_skills": [], "learning_roadmap": "N/A", "recommended_courses": [], "certification_suggestions": [], "promotion_readiness_score": 50, "hiring_recommendation": "Further assessment required."}
        rec = SkillGapAnalysis(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, target_role=target_role, current_skills=json.dumps(current_skills), required_skills=json.dumps(required_skills), missing_skills=json.dumps(data.get("missing_skills", [])), learning_roadmap=data.get("learning_roadmap"), recommended_courses=json.dumps(data.get("recommended_courses", [])), certification_suggestions=json.dumps(data.get("certification_suggestions", [])), promotion_readiness_score=int(data.get("promotion_readiness_score", 50)), hiring_recommendation=data.get("hiring_recommendation"))
        self.db.add(rec)
        await self.db.commit()
        await self.db.refresh(rec)
        return rec


class ShiftPlannerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def create_shift_plan(self, company_id: uuid.UUID, department: Optional[str], plan_type: str, period_start: date, period_end: date, employees: list, constraints: str, model: Optional[str] = None) -> ShiftPlan:
        period_str = f"{period_start} to {period_end}"
        try:
            res = await self.llm.complete(PromptLibrary.ai_shift_planner_user(str(employees), period_str, constraints), system=PromptLibrary.AI_SHIFT_PLANNER, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("ShiftPlanner failed: %s", e)
            data = {"entries": [], "ai_optimization_notes": "Fallback: manual scheduling required."}
        plan = ShiftPlan(id=uuid.uuid4(), company_id=company_id, department=department, plan_type=plan_type, period_start=period_start, period_end=period_end, ai_optimization_notes=data.get("ai_optimization_notes"))
        self.db.add(plan)
        await self.db.flush()
        for entry_data in data.get("entries", []):
            try:
                emp_id = uuid.UUID(entry_data.get("employee_id", str(employees[0]))) if employees else uuid.uuid4()
            except Exception:
                emp_id = employees[0] if employees else uuid.uuid4()
            entry = ShiftPlanEntry(id=uuid.uuid4(), plan_id=plan.id, employee_id=emp_id, shift_date=date.fromisoformat(entry_data.get("shift_date", str(period_start))), shift_type=entry_data.get("shift_type", "DAY"), notes=entry_data.get("notes"))
            self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(plan)
        return plan


class DigitalTwinService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def generate_or_update_twin(self, company_id: uuid.UUID, employee_id: uuid.UUID, employee_data: dict, model: Optional[str] = None) -> EmployeeDigitalTwin:
        try:
            res = await self.llm.complete(PromptLibrary.ai_digital_twin_user(str(employee_data)), system=PromptLibrary.AI_DIGITAL_TWIN_FORECAST, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("DigitalTwin generation failed: %s", e)
            data = {"performance_score": 70, "career_growth_score": 65, "productivity_index": 70, "attendance_score": 80, "ai_performance_forecast": "Auto-generated standard forecast."}
        stmt = select(EmployeeDigitalTwin).where(EmployeeDigitalTwin.employee_id == employee_id)
        result = await self.db.execute(stmt)
        twin = result.scalar_one_or_none()
        if not twin:
            twin = EmployeeDigitalTwin(id=uuid.uuid4(), employee_id=employee_id, company_id=company_id)
            self.db.add(twin)
        twin.performance_score = int(data.get("performance_score", 70))
        twin.career_growth_score = int(data.get("career_growth_score", 65))
        twin.productivity_index = int(data.get("productivity_index", 70))
        twin.attendance_score = int(data.get("attendance_score", 80))
        twin.ai_performance_forecast = data.get("ai_performance_forecast")
        twin.skills_summary = json.dumps(employee_data.get("skills", []))
        await self.db.commit()
        await self.db.refresh(twin)
        return twin
