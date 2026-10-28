"""Internal job eligibility, applications, and manager approval gates."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.talent_marketplace import InternalJobApplication, InternalJobOpening
from app.services.performance_service import PerformanceEnterpriseService


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(0, months)


class InternalJobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Active employee not found in this tenant.")
        return employee

    async def _opening(self, opening_id: uuid.UUID, company_id: uuid.UUID) -> InternalJobOpening:
        opening = (await self.session.execute(select(InternalJobOpening).where(
            InternalJobOpening.id == opening_id, InternalJobOpening.company_id == company_id,
        ))).scalar_one_or_none()
        if opening is None:
            raise LookupError("Internal job opening not found.")
        return opening

    async def create_opening(
        self, *, company_id: uuid.UUID, title: str, department: str, designation: str,
        description: str, min_tenure_months: int = 0,
        min_performance_score: float | None = None, closes_at: datetime | None = None,
        created_by: uuid.UUID | None = None,
    ) -> InternalJobOpening:
        if min_tenure_months < 0:
            raise ValueError("Minimum tenure cannot be negative.")
        if min_performance_score is not None and not 0 <= min_performance_score <= 5:
            raise ValueError("Minimum performance score must be between 0 and 5.")
        opening = InternalJobOpening(
            id=uuid.uuid4(), company_id=company_id, title=title.strip(), department=department.strip(),
            designation=designation.strip(), description=description.strip(),
            min_tenure_months=min_tenure_months,
            min_performance_score=Decimal(str(min_performance_score)) if min_performance_score is not None else None,
            closes_at=closes_at, created_by=created_by,
        )
        self.session.add(opening)
        await self.session.commit()
        return opening

    async def check_eligibility(
        self, opening_id: uuid.UUID, *, company_id: uuid.UUID,
        employee_id: uuid.UUID, as_of: date | None = None,
    ) -> dict:
        opening = await self._opening(opening_id, company_id)
        employee = await self._employee(employee_id, company_id)
        as_of = as_of or date.today()
        tenure = _months_between(employee.joining_date, as_of)
        score = await PerformanceEnterpriseService(self.session).latest_employee_score(
            company_id=company_id, employee_id=employee_id,
        )
        reasons = []
        if opening.status != "OPEN":
            reasons.append("OPENING_NOT_OPEN")
        if opening.closes_at:
            closes_at = opening.closes_at.replace(tzinfo=UTC) if opening.closes_at.tzinfo is None else opening.closes_at
            if closes_at.astimezone(UTC) < datetime.now(UTC):
                reasons.append("OPENING_CLOSED")
        if tenure < opening.min_tenure_months:
            reasons.append("MINIMUM_TENURE_NOT_MET")
        if opening.min_performance_score is not None:
            if score is None:
                reasons.append("PERFORMANCE_SCORE_NOT_AVAILABLE")
            elif score < opening.min_performance_score:
                reasons.append("MINIMUM_PERFORMANCE_NOT_MET")
        return {
            "eligible": not reasons, "reasons": reasons, "tenure_months": tenure,
            "performance_score": float(score) if score is not None else None,
            "minimum_tenure_months": opening.min_tenure_months,
            "minimum_performance_score": float(opening.min_performance_score) if opening.min_performance_score is not None else None,
        }

    async def apply(
        self, opening_id: uuid.UUID, *, company_id: uuid.UUID,
        employee_id: uuid.UUID, cover_note: str | None = None,
    ) -> InternalJobApplication:
        await self._opening(opening_id, company_id)
        existing = (await self.session.execute(select(InternalJobApplication).where(
            InternalJobApplication.opening_id == opening_id,
            InternalJobApplication.employee_id == employee_id,
            InternalJobApplication.company_id == company_id,
        ))).scalar_one_or_none()
        if existing:
            return existing
        eligibility = await self.check_eligibility(opening_id, company_id=company_id, employee_id=employee_id)
        application = InternalJobApplication(
            id=uuid.uuid4(), company_id=company_id, opening_id=opening_id, employee_id=employee_id,
            status="PENDING_MANAGER" if eligibility["eligible"] else "INELIGIBLE",
            eligibility_json=eligibility, tenure_months_at_application=eligibility["tenure_months"],
            performance_score=Decimal(str(eligibility["performance_score"])) if eligibility["performance_score"] is not None else None,
            cover_note=cover_note,
        )
        self.session.add(application)
        await self.session.commit()
        return application

    async def manager_decision(
        self, application_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_user_id: uuid.UUID, approved: bool, reason: str | None = None,
        actor_role: str = "manager",
    ) -> InternalJobApplication:
        application = (await self.session.execute(select(InternalJobApplication).where(
            InternalJobApplication.id == application_id, InternalJobApplication.company_id == company_id,
        ))).scalar_one_or_none()
        if application is None:
            raise LookupError("Internal job application not found.")
        if application.status != "PENDING_MANAGER" or not application.eligibility_json.get("eligible"):
            raise ValueError("Application is not awaiting an eligible manager decision.")
        employee = await self._employee(application.employee_id, company_id)
        manager_id = employee.reporting_manager_id or employee.manager_id
        manager = await self.session.get(Employee, manager_id) if manager_id else None
        is_manager = manager is not None and manager.company_id == company_id and manager.user_id == actor_user_id
        is_hr_fallback = manager is None and actor_role.lower() in {"admin", "hr_admin", "super_admin"}
        if not (is_manager or is_hr_fallback):
            raise PermissionError("Only the employee's reporting manager may decide this application.")
        application.status = "MANAGER_APPROVED" if approved else "MANAGER_REJECTED"
        application.manager_approved_by = actor_user_id
        application.manager_decision_at = datetime.now(UTC)
        application.manager_decision_reason = reason
        await self.session.commit()
        return application
