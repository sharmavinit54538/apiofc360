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


class OrgTwinSimulationService:
    """Read-only organization simulations with a persisted audit snapshot."""

    SCENARIOS = {"RESTRUCTURING", "BUDGET_CUT", "KEY_PERSON_EXIT", "PROJECT_SKILLS", "SPAN_OF_CONTROL"}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _spans(employees: list, excluded: set[uuid.UUID] | None = None) -> list[dict[str, Any]]:
        excluded = excluded or set()
        counts: dict[uuid.UUID, int] = {}
        names: dict[uuid.UUID, str] = {}
        for employee in employees:
            names[employee.id] = f"{employee.first_name} {employee.last_name}".strip()
            if employee.id in excluded:
                continue
            manager_id = employee.reporting_manager_id or employee.manager_id
            if manager_id:
                counts[manager_id] = counts.get(manager_id, 0) + 1
        return [
            {"manager_employee_id": str(manager_id), "manager_name": names.get(manager_id), "direct_reports": count}
            for manager_id, count in sorted(counts.items(), key=lambda item: str(item[0]))
        ]

    async def simulate(
        self, *, company_id: uuid.UUID, scenario_type: str, name: str,
        parameters: dict[str, Any], created_by: uuid.UUID | None = None,
    ) -> OrgTwinSimulation:
        from collections import defaultdict
        from decimal import Decimal
        from app.models.compensation import CompensationBand, EmployeeCompensationBand
        from app.models.digital_twin import OrgTwinSimulation
        from app.models.employee import Employee
        from app.models.employee_skill import EmployeeSkill

        scenario = scenario_type.strip().upper()
        if scenario not in self.SCENARIOS:
            raise ValueError(f"Unsupported scenario. Choose one of {sorted(self.SCENARIOS)}.")
        employees = (await self.db.execute(select(Employee).where(
            Employee.company_id == company_id, Employee.status == "ACTIVE",
            Employee.is_deleted.is_(False),
        ))).scalars().all()
        by_id = {employee.id: employee for employee in employees}
        assignments = (await self.db.execute(
            select(EmployeeCompensationBand, CompensationBand)
            .join(CompensationBand, CompensationBand.id == EmployeeCompensationBand.band_id)
            .where(EmployeeCompensationBand.company_id == company_id,
                   EmployeeCompensationBand.is_current.is_(True),
                   CompensationBand.company_id == company_id)
        )).all()
        salary_by_employee = {assignment.employee_id: int(assignment.annual_salary_paise) for assignment, _ in assignments}
        currency_by_employee = {assignment.employee_id: band.currency for assignment, band in assignments}
        for employee in employees:
            salary_by_employee.setdefault(employee.id, int(Decimal(str(employee.ctc or 0)) * 100))
        skill_rows = (await self.db.execute(
            select(EmployeeSkill).join(Employee, Employee.id == EmployeeSkill.employee_id).where(
                Employee.company_id == company_id, Employee.is_deleted.is_(False),
            )
        )).scalars().all()
        skills_by_employee: dict[uuid.UUID, dict[str, str | None]] = defaultdict(dict)
        for skill in skill_rows:
            if skill.employee_id in by_id:
                skills_by_employee[skill.employee_id][skill.skill_name.strip().casefold()] = skill.proficiency

        baseline = {
            "headcount": len(employees),
            "annual_payroll_paise": sum(salary_by_employee.values()),
            "manager_spans": self._spans(employees),
            "skill_coverage": {
                skill: sum(skill in skills_by_employee[employee.id] for employee in employees)
                for skill in sorted({skill for values in skills_by_employee.values() for skill in values})
            },
        }
        impact: dict[str, Any] = {}
        recommendations: list[str] = []
        warnings: list[str] = []

        def employee_ids(raw_values: Any, field_name: str) -> set[uuid.UUID]:
            if not isinstance(raw_values, list):
                raise ValueError(f"{field_name} must be a list of employee UUIDs.")
            parsed = {uuid.UUID(str(value)) for value in raw_values}
            unknown = parsed - set(by_id)
            if unknown:
                raise LookupError(f"Employees not found in the current tenant: {sorted(str(value) for value in unknown)}")
            return parsed

        if scenario == "RESTRUCTURING":
            excluded = employee_ids(parameters.get("excluded_employee_ids", []), "excluded_employee_ids")
            moves = parameters.get("moves", [])
            if not isinstance(moves, list):
                raise ValueError("moves must be a list.")
            department_after: dict[str, int] = defaultdict(int)
            for employee in employees:
                if employee.id not in excluded:
                    department_after[employee.department or "UNASSIGNED"] += 1
            validated_moves = []
            for move in moves:
                employee_id = uuid.UUID(str(move.get("employee_id")))
                if employee_id not in by_id:
                    raise LookupError(f"Employee '{employee_id}' not found in the current tenant.")
                target_manager = move.get("to_manager_employee_id")
                if target_manager is not None:
                    target_manager = uuid.UUID(str(target_manager))
                    if target_manager not in by_id or target_manager in excluded or target_manager == employee_id:
                        raise ValueError("Target manager must be another active employee in the current tenant.")
                target_department = str(move.get("to_department") or by_id[employee_id].department)
                if employee_id not in excluded:
                    department_after[by_id[employee_id].department or "UNASSIGNED"] -= 1
                    department_after[target_department] += 1
                validated_moves.append({
                    "employee_id": str(employee_id), "to_manager_employee_id": str(target_manager) if target_manager else None,
                    "to_department": target_department,
                })
            impact = {
                "excluded_employee_ids": sorted(str(value) for value in excluded),
                "moves": validated_moves,
                "headcount_after": len(employees) - len(excluded),
                "annual_payroll_after_paise": sum(value for key, value in salary_by_employee.items() if key not in excluded),
                "annual_payroll_delta_paise": -sum(salary_by_employee[value] for value in excluded),
                "department_headcount_after": dict(sorted(department_after.items())),
                "manager_spans_after": self._spans(employees, excluded),
            }
            recommendations.append("Review every proposed move and exclusion with HR, Finance and the affected employee before execution.")

        elif scenario == "BUDGET_CUT":
            cut = Decimal(str(parameters.get("cut_percentage", 10)))
            if not 0 <= cut <= 100:
                raise ValueError("cut_percentage must be between 0 and 100.")
            non_employee_savings = int(parameters.get("non_employee_cost_reduction_paise", 0))
            if non_employee_savings < 0:
                raise ValueError("non_employee_cost_reduction_paise cannot be negative.")
            target = int(Decimal(baseline["annual_payroll_paise"]) * cut / 100)
            remaining = max(0, target - non_employee_savings)
            department_costs: dict[str, int] = defaultdict(int)
            for employee in employees:
                department_costs[employee.department or "UNASSIGNED"] += salary_by_employee[employee.id]
            impact = {
                "cut_percentage": float(cut), "target_reduction_paise": target,
                "non_employee_cost_reduction_paise": non_employee_savings,
                "remaining_payroll_budget_gap_paise": remaining,
                "annual_payroll_baseline_paise": baseline["annual_payroll_paise"],
                "department_cost_exposure": [
                    {"department": department, "annual_payroll_paise": cost,
                     "proportional_review_allocation_paise": int(Decimal(remaining) * cost / max(1, baseline["annual_payroll_paise"]))}
                    for department, cost in sorted(department_costs.items())
                ],
            }
            recommendations.extend([
                "Prioritize verified non-employee savings, vacant-position review and discretionary spend before employment actions.",
                "Do not interpret proportional allocations as individual termination recommendations; conduct legal and employee-impact review.",
            ])

        elif scenario == "KEY_PERSON_EXIT":
            exits = employee_ids(parameters.get("key_employee_ids", []), "key_employee_ids")
            if not exits:
                raise ValueError("key_employee_ids must contain at least one employee.")
            exit_impacts = []
            for employee_id in sorted(exits, key=str):
                employee = by_id[employee_id]
                direct_reports = [item for item in employees if item.id not in exits and (item.reporting_manager_id or item.manager_id) == employee_id]
                lost_skills = set(skills_by_employee[employee_id])
                successors = []
                for candidate in employees:
                    if candidate.id in exits:
                        continue
                    overlap = lost_skills & set(skills_by_employee[candidate.id])
                    if overlap:
                        successors.append({
                            "employee_id": str(candidate.id),
                            "name": f"{candidate.first_name} {candidate.last_name}".strip(),
                            "shared_skills": sorted(overlap),
                            "coverage_score": round(len(overlap) / max(1, len(lost_skills)), 4),
                        })
                successors.sort(key=lambda row: (-row["coverage_score"], row["employee_id"]))
                exit_impacts.append({
                    "employee_id": str(employee_id),
                    "name": f"{employee.first_name} {employee.last_name}".strip(),
                    "department": employee.department,
                    "direct_reports_requiring_reassignment": [str(item.id) for item in direct_reports],
                    "skills_at_risk": sorted(lost_skills),
                    "annual_payroll_delta_paise": -salary_by_employee[employee_id],
                    "potential_internal_successors": successors[:5],
                })
            impact = {
                "key_person_impacts": exit_impacts,
                "headcount_after": len(employees) - len(exits),
                "annual_payroll_after_paise": sum(value for key, value in salary_by_employee.items() if key not in exits),
                "skill_coverage_after": {
                    skill: sum(skill in skills_by_employee[employee.id] for employee in employees if employee.id not in exits)
                    for skill in baseline["skill_coverage"]
                },
            }
            recommendations.append("Validate successor readiness and consent, document knowledge transfer, and reassign every direct report before any approved exit.")

        elif scenario == "PROJECT_SKILLS":
            raw_requirements = parameters.get("required_skills", {})
            if isinstance(raw_requirements, list):
                requirements = {str(skill).strip().casefold(): 1 for skill in raw_requirements}
            elif isinstance(raw_requirements, dict):
                requirements = {str(skill).strip().casefold(): int(count) for skill, count in raw_requirements.items()}
            else:
                raise ValueError("required_skills must be an object or list.")
            if not requirements or any(not skill or count < 1 for skill, count in requirements.items()):
                raise ValueError("Each required skill must have a positive headcount.")
            gaps = []
            total_required = total_available = 0
            for skill, required in sorted(requirements.items()):
                candidates = [{
                    "employee_id": str(employee.id),
                    "name": f"{employee.first_name} {employee.last_name}".strip(),
                    "proficiency": skills_by_employee[employee.id][skill],
                } for employee in employees if skill in skills_by_employee[employee.id]]
                available = len(candidates)
                total_required += required
                total_available += min(required, available)
                gaps.append({
                    "skill": skill, "required_headcount": required,
                    "available_headcount": available, "gap": max(0, required - available),
                    "internal_candidates": candidates,
                })
            impact = {
                "skills": gaps, "total_required_capacity": total_required,
                "matched_capacity": total_available,
                "project_readiness_pct": round(total_available * 100 / total_required, 2),
            }
            recommendations.append("Confirm employee availability and proficiency before staffing; close remaining gaps through learning or approved hiring.")

        else:  # SPAN_OF_CONTROL
            minimum = int(parameters.get("minimum_direct_reports", 4))
            maximum = int(parameters.get("maximum_direct_reports", 10))
            if minimum < 1 or maximum < minimum:
                raise ValueError("Span bounds must be positive and maximum must be >= minimum.")
            spans = baseline["manager_spans"]
            exceptions = []
            for span in spans:
                count = span["direct_reports"]
                if count < minimum or count > maximum:
                    exceptions.append({**span, "issue": "SPAN_TOO_SMALL" if count < minimum else "SPAN_TOO_LARGE"})
            import math
            impact = {
                "minimum_direct_reports": minimum, "maximum_direct_reports": maximum,
                "manager_spans": spans, "exceptions": exceptions,
                "estimated_managers_required_at_max_span": math.ceil(len(employees) / maximum) if employees else 0,
                "current_managers_with_direct_reports": len(spans),
            }
            recommendations.append("Review exceptions with organizational context; span targets are diagnostic and do not automatically justify reorganization.")

        result = {
            "scenario_type": scenario, "simulation_only": True, "impact": impact,
            "recommendations": recommendations,
            "warnings": warnings + ["Simulation only: no organization, employee, budget or payroll records were changed."],
            "requires_human_approval": True,
        }
        simulation = OrgTwinSimulation(
            id=uuid.uuid4(), company_id=company_id, scenario_type=scenario,
            name=name.strip() or f"{scenario} simulation", input_json=parameters,
            baseline_json=baseline, result_json=result, status="COMPLETED",
            created_by=created_by,
        )
        self.db.add(simulation)
        await self.db.commit()
        await self.db.refresh(simulation)
        return simulation
