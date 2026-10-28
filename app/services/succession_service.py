"""Succession readiness, development actions, and leadership risk analytics."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.succession import CriticalRole, SuccessorSlate, SuccessionDevelopmentAction


def _score(value: float | Decimal, name: str) -> Decimal:
    result = Decimal(str(value))
    if result < 0 or result > 100:
        raise ValueError(f"{name} must be between 0 and 100.")
    return result


def readiness_score(performance: Decimal, potential: Decimal, skill_coverage: Decimal) -> Decimal:
    """Weighted, explainable readiness score (40% performance, 30% potential, 30% skills)."""
    return ((performance * Decimal("0.40")) + (potential * Decimal("0.30")) + (skill_coverage * Decimal("0.30"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


def readiness_category(score: Decimal) -> str:
    if score >= 80:
        return "READY_NOW"
    if score >= 60:
        return "READY_1_2_YRS"
    return "READY_3_5_YRS"


class SuccessionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted.is_(False),
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Employee not found in this tenant.")
        return employee

    async def _role(self, role_id: uuid.UUID, company_id: uuid.UUID) -> CriticalRole:
        role = (await self.session.execute(select(CriticalRole).options(
            selectinload(CriticalRole.successors),
        ).where(CriticalRole.id == role_id, CriticalRole.company_id == company_id))).scalar_one_or_none()
        if role is None:
            raise LookupError("Critical role not found.")
        return role

    async def create_critical_role(
        self, *, company_id: uuid.UUID, title: str, department: str,
        incumbent_employee_id: uuid.UUID | None = None,
        vacancy_risk_score: float = 50, business_impact_score: float = 50,
    ) -> CriticalRole:
        if incumbent_employee_id:
            await self._employee(incumbent_employee_id, company_id)
        vacancy = _score(vacancy_risk_score, "Vacancy risk")
        impact = _score(business_impact_score, "Business impact")
        combined = vacancy * Decimal("0.5") + impact * Decimal("0.5")
        risk = "CRITICAL" if combined >= 80 else "HIGH" if combined >= 65 else "MEDIUM" if combined >= 40 else "LOW"
        role = CriticalRole(
            id=uuid.uuid4(), company_id=company_id, title=title.strip(), department=department.strip(),
            incumbent_employee_id=incumbent_employee_id, vacancy_risk_score=vacancy,
            business_impact_score=impact, risk_level=risk, is_critical=True,
        )
        self.session.add(role)
        await self.session.commit()
        return role

    async def add_successor(
        self, role_id: uuid.UUID, *, company_id: uuid.UUID, employee_id: uuid.UUID,
        performance_score: float, potential_score: float, skill_coverage_score: float,
        notes: str | None = None,
    ) -> SuccessorSlate:
        role = await self._role(role_id, company_id)
        await self._employee(employee_id, company_id)
        if role.incumbent_employee_id == employee_id:
            raise ValueError("The incumbent cannot be their own successor.")
        performance = _score(performance_score, "Performance")
        potential = _score(potential_score, "Potential")
        skills = _score(skill_coverage_score, "Skill coverage")
        score = readiness_score(performance, potential, skills)
        existing = (await self.session.execute(select(SuccessorSlate).where(
            SuccessorSlate.role_id == role_id, SuccessorSlate.employee_id == employee_id,
        ))).scalar_one_or_none()
        slate = existing or SuccessorSlate(id=uuid.uuid4(), company_id=company_id, role_id=role_id, employee_id=employee_id)
        slate.performance_score = performance
        slate.potential_score = potential
        slate.skill_coverage_score = skills
        slate.readiness_score = score
        slate.readiness_category = readiness_category(score)
        slate.notes = notes
        self.session.add(slate)
        await self.session.commit()
        return slate

    async def add_development_action(
        self, slate_id: uuid.UUID, *, company_id: uuid.UUID, title: str,
        due_date: date, description: str | None = None,
        owner_employee_id: uuid.UUID | None = None,
    ) -> SuccessionDevelopmentAction:
        slate = (await self.session.execute(select(SuccessorSlate).where(
            SuccessorSlate.id == slate_id, SuccessorSlate.company_id == company_id,
        ))).scalar_one_or_none()
        if slate is None:
            raise LookupError("Successor slate not found.")
        if owner_employee_id:
            await self._employee(owner_employee_id, company_id)
        action = SuccessionDevelopmentAction(
            id=uuid.uuid4(), company_id=company_id, slate_id=slate_id, title=title.strip(),
            description=description, due_date=due_date, owner_employee_id=owner_employee_id,
        )
        self.session.add(action)
        await self.session.commit()
        return action

    async def update_development_action(
        self, action_id: uuid.UUID, *, company_id: uuid.UUID,
        progress_percentage: int, evidence_reference: str | None = None,
    ) -> SuccessionDevelopmentAction:
        if progress_percentage < 0 or progress_percentage > 100:
            raise ValueError("Progress must be between 0 and 100.")
        action = (await self.session.execute(select(SuccessionDevelopmentAction).where(
            SuccessionDevelopmentAction.id == action_id,
            SuccessionDevelopmentAction.company_id == company_id,
        ))).scalar_one_or_none()
        if action is None:
            raise LookupError("Development action not found.")
        action.progress_percentage = progress_percentage
        action.evidence_reference = evidence_reference or action.evidence_reference
        action.status = "COMPLETED" if progress_percentage == 100 else "IN_PROGRESS" if progress_percentage else "NOT_STARTED"
        action.completed_at = datetime.now(UTC) if progress_percentage == 100 else None
        await self.session.commit()
        return action

    async def leadership_risk_map(self, *, company_id: uuid.UUID) -> list[dict]:
        roles = (await self.session.execute(select(CriticalRole).options(
            selectinload(CriticalRole.successors),
        ).where(CriticalRole.company_id == company_id, CriticalRole.is_critical.is_(True))
        .execution_options(populate_existing=True))).scalars().all()
        result = []
        for role in roles:
            ready_now = sum(slate.readiness_category == "READY_NOW" for slate in role.successors)
            ready_future = sum(slate.readiness_category in {"READY_NOW", "READY_1_2_YRS"} for slate in role.successors)
            if not role.successors:
                coverage_risk = "CRITICAL"
            elif not ready_now:
                coverage_risk = "HIGH"
            elif ready_future < 2:
                coverage_risk = "MEDIUM"
            else:
                coverage_risk = "LOW"
            result.append({
                "role_id": str(role.id), "title": role.title, "department": role.department,
                "inherent_risk": role.risk_level, "coverage_risk": coverage_risk,
                "successor_count": len(role.successors), "ready_now_count": ready_now,
                "ready_within_two_years_count": ready_future,
                "successors": [
                    {"employee_id": str(slate.employee_id), "readiness_score": float(slate.readiness_score),
                     "readiness_category": slate.readiness_category}
                    for slate in sorted(role.successors, key=lambda item: item.readiness_score, reverse=True)
                ],
            })
        priority = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        return sorted(result, key=lambda item: (priority[item["coverage_risk"]], item["title"]))
