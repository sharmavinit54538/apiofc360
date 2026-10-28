"""Confidential grievance and POSH workflows.

All methods take an explicit tenant id.  Service-level permission checks are
intentional: confidentiality must not depend only on a route dependency.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.user import User
from app.models.grievance_posh import (
    GrievanceCase,
    GrievanceCaseEvent,
    ICCCommittee,
    ICCMember,
    POSHAnnualReturn,
    POSHComplaint,
    POSHEvidence,
    POSHTrainingRecord,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _uuid_set(values: Iterable[uuid.UUID | str] | None) -> set[uuid.UUID]:
    result: set[uuid.UUID] = set()
    for value in values or []:
        result.add(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    return result


class ConfidentialityError(PermissionError):
    """Raised when a user is not permitted to access a restricted case."""


class GrievancePOSHService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _employee_user_ids(self, employee_ids: Iterable[uuid.UUID | str]) -> set[uuid.UUID]:
        ids = _uuid_set(employee_ids)
        if not ids:
            return set()
        rows = (await self.session.execute(select(Employee).where(Employee.id.in_(ids)))).scalars().all()
        return {row.user_id for row in rows if row.user_id is not None}

    async def _validate_reporter(
        self, *, company_id: uuid.UUID,
        employee_id: uuid.UUID | None, user_id: uuid.UUID | None,
    ) -> None:
        employee = None
        if employee_id is not None:
            employee = (await self.session.execute(select(Employee).where(
                Employee.id == employee_id, Employee.company_id == company_id,
                Employee.is_deleted.is_(False),
            ))).scalar_one_or_none()
            if employee is None:
                raise ValueError("Reporter employee must belong to the complaint tenant.")
        if user_id is not None:
            user = (await self.session.execute(select(User).where(
                User.id == user_id, User.company_id == company_id, User.is_active.is_(True),
            ))).scalar_one_or_none()
            if user is None:
                raise ValueError("Reporter user must be an active user of the complaint tenant.")
            if employee is not None and employee.user_id != user_id:
                raise ValueError("Reporter employee and user references do not match.")

    async def _accused_users(
        self,
        accused_user_ids: Iterable[uuid.UUID | str] | None = None,
        accused_employee_ids: Iterable[uuid.UUID | str] | None = None,
        accused_manager_ids: Iterable[uuid.UUID | str] | None = None,
    ) -> list[str]:
        """Resolve employee/manager references to user ids used by access checks."""
        employee_refs = _uuid_set(accused_employee_ids) | _uuid_set(accused_manager_ids)
        users = _uuid_set(accused_user_ids) | await self._employee_user_ids(employee_refs)
        # Keep unresolved manager references as well.  This is safe (more restrictive) and
        # supports callers that supplied manager user ids directly.
        users |= _uuid_set(accused_manager_ids)
        return [str(value) for value in sorted(users, key=str)]

    @staticmethod
    def _receipt() -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _assert_not_accused(case: GrievanceCase | POSHComplaint, actor_id: uuid.UUID | None) -> None:
        accused = _uuid_set(case.accused_user_ids or [])
        if actor_id is not None and actor_id in accused:
            raise ConfidentialityError("Accused users and managers cannot access or investigate this case.")

    async def create_grievance(
        self,
        *,
        company_id: uuid.UUID,
        category: str,
        subject: str,
        description: str,
        reporter_employee_id: uuid.UUID | None = None,
        reporter_user_id: uuid.UUID | None = None,
        anonymous: bool = False,
        confidential: bool = True,
        sla_hours: int = 72,
        accused_user_ids: Iterable[uuid.UUID | str] | None = None,
        accused_employee_ids: Iterable[uuid.UUID | str] | None = None,
        accused_manager_ids: Iterable[uuid.UUID | str] | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> GrievanceCase:
        if not anonymous and reporter_employee_id is None and reporter_user_id is None:
            raise ValueError("A reporter is required unless the grievance is anonymous.")
        if sla_hours < 1:
            raise ValueError("SLA must be at least one hour.")
        if not category.strip() or not subject.strip() or not description.strip():
            raise ValueError("Category, subject and description are required.")
        if not anonymous:
            await self._validate_reporter(
                company_id=company_id, employee_id=reporter_employee_id, user_id=reporter_user_id,
            )
        token, token_hash = self._receipt() if anonymous else (None, None)
        case = GrievanceCase(
            id=uuid.uuid4(),
            company_id=company_id,
            case_number=f"GRV-{uuid.uuid4().hex[:12].upper()}",
            reporter_employee_id=None if anonymous else reporter_employee_id,
            reporter_user_id=None if anonymous else reporter_user_id,
            is_anonymous=anonymous,
            is_confidential=confidential,
            receipt_token_hash=token_hash,
            category=category.strip().upper(),
            subject=subject.strip(),
            description=description.strip(),
            accused_user_ids=await self._accused_users(accused_user_ids, accused_employee_ids, accused_manager_ids),
            priority="NORMAL",
            status="OPEN",
            sla_due_at=_now() + timedelta(hours=sla_hours),
        )
        self.session.add(case)
        await self.session.flush()
        self.session.add(GrievanceCaseEvent(
            id=uuid.uuid4(), case_id=case.id, event_type="FILED", actor_id=actor_id,
            notes="Confidential grievance filed.", event_metadata={"anonymous": anonymous},
        ))
        await self.session.commit()
        # The plain receipt is deliberately transient and is returned only once.
        case.receipt_token = token
        return case

    async def _grievance(self, case_id: uuid.UUID, company_id: uuid.UUID) -> GrievanceCase:
        case = (await self.session.execute(
            select(GrievanceCase).where(GrievanceCase.id == case_id, GrievanceCase.company_id == company_id)
        )).scalar_one_or_none()
        if case is None:
            raise LookupError("Grievance not found.")
        return case

    async def get_grievance(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_id: uuid.UUID | None, actor_role: str = "employee",
        receipt_token: str | None = None,
    ) -> GrievanceCase:
        case = await self._grievance(case_id, company_id)
        self._assert_not_accused(case, actor_id)
        privileged = actor_role.lower() in {"admin", "hr_admin", "super_admin", "posh_admin"}
        reporter = actor_id is not None and actor_id == case.reporter_user_id
        investigator = actor_id is not None and actor_id == case.investigator_id
        receipt_ok = bool(
            receipt_token and case.receipt_token_hash and
            secrets.compare_digest(hashlib.sha256(receipt_token.encode()).hexdigest(), case.receipt_token_hash)
        )
        if not (privileged or reporter or investigator or receipt_ok):
            raise ConfidentialityError("You do not have access to this confidential grievance.")
        return case

    @staticmethod
    def serialize_grievance(case: GrievanceCase, *, include_reporter: bool = False) -> dict[str, Any]:
        # Anonymous identity is withheld even from investigators and HR exports.
        reveal_reporter = include_reporter and not case.is_anonymous
        return {
            "id": str(case.id), "case_number": case.case_number,
            "company_id": str(case.company_id) if case.company_id else None,
            "category": case.category, "subject": case.subject, "description": case.description,
            "is_anonymous": case.is_anonymous, "is_confidential": case.is_confidential,
            "reporter_employee_id": str(case.reporter_employee_id) if reveal_reporter and case.reporter_employee_id else None,
            "reporter_user_id": str(case.reporter_user_id) if reveal_reporter and case.reporter_user_id else None,
            "status": case.status, "priority": case.priority,
            "sla_due_at": _iso(case.sla_due_at), "escalated_at": _iso(case.escalated_at),
            "escalation_level": case.escalation_level,
            "investigator_id": str(case.investigator_id) if case.investigator_id else None,
            "resolution": case.resolution, "resolved_at": _iso(case.resolved_at),
            "appeal_status": case.appeal_status, "appeal_reason": case.appeal_reason,
            "appealed_at": _iso(case.appealed_at), "appeal_resolution": case.appeal_resolution,
            "created_at": _iso(case.created_at),
        }

    async def assign_investigator(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID,
        investigator_id: uuid.UUID, actor_id: uuid.UUID, actor_role: str = "employee",
    ) -> GrievanceCase:
        if actor_role.lower() not in {"admin", "hr_admin", "super_admin", "posh_admin"}:
            raise ConfidentialityError("Only HR/POSH administrators may assign an investigator.")
        case = await self._grievance(case_id, company_id)
        self._assert_not_accused(case, actor_id)
        self._assert_not_accused(case, investigator_id)
        investigator = (await self.session.execute(select(User).where(
            User.id == investigator_id, User.company_id == company_id, User.is_active.is_(True),
        ))).scalar_one_or_none()
        if investigator is None:
            raise ValueError("Investigator must be an active user of the grievance tenant.")
        case.investigator_id = investigator_id
        case.assigned_at = _now()
        case.status = "IN_REVIEW"
        self.session.add(GrievanceCaseEvent(
            id=uuid.uuid4(), case_id=case.id, event_type="INVESTIGATOR_ASSIGNED",
            actor_id=actor_id, event_metadata={"investigator_id": str(investigator_id)},
        ))
        await self.session.commit()
        return case

    async def resolve_grievance(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID,
        resolution: str, actor_id: uuid.UUID, actor_role: str = "employee",
    ) -> GrievanceCase:
        case = await self._grievance(case_id, company_id)
        self._assert_not_accused(case, actor_id)
        privileged = actor_role.lower() in {"admin", "hr_admin", "super_admin", "posh_admin"}
        if not privileged and actor_id != case.investigator_id:
            raise ConfidentialityError("Only HR or the assigned investigator may resolve this grievance.")
        if not resolution.strip():
            raise ValueError("Resolution is required.")
        case.resolution = resolution.strip()
        case.resolved_by = actor_id
        case.resolved_at = _now()
        case.status = "RESOLVED"
        self.session.add(GrievanceCaseEvent(
            id=uuid.uuid4(), case_id=case.id, event_type="RESOLVED", actor_id=actor_id,
        ))
        await self.session.commit()
        return case

    async def appeal_grievance(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID, reason: str,
        actor_id: uuid.UUID | None = None, receipt_token: str | None = None,
    ) -> GrievanceCase:
        case = await self._grievance(case_id, company_id)
        receipt_ok = bool(
            receipt_token and case.receipt_token_hash and
            secrets.compare_digest(hashlib.sha256(receipt_token.encode()).hexdigest(), case.receipt_token_hash)
        )
        reporter_ok = actor_id is not None and case.reporter_user_id is not None and actor_id == case.reporter_user_id
        if not reporter_ok and not receipt_ok:
            raise ConfidentialityError("Only the employee who filed the grievance may appeal.")
        if len(reason.strip()) < 5:
            raise ValueError("Appeal reason must contain at least five characters.")
        if case.status not in {"RESOLVED", "CLOSED"} or case.resolved_at is None:
            raise ValueError("An appeal is allowed after resolution.")
        if case.appeal_status == "PENDING":
            raise ValueError("An appeal is already pending.")
        case.appeal_reason = reason.strip()
        case.appealed_at = _now()
        case.appeal_status = "PENDING"
        case.status = "APPEALED"
        self.session.add(GrievanceCaseEvent(
            id=uuid.uuid4(), case_id=case.id, event_type="APPEALED", actor_id=actor_id,
        ))
        await self.session.commit()
        return case

    async def decide_appeal(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID, decision: str,
        resolution: str, actor_id: uuid.UUID, actor_role: str = "employee",
    ) -> GrievanceCase:
        if actor_role.lower() not in {"admin", "hr_admin", "super_admin", "posh_admin"}:
            raise ConfidentialityError("Only HR/POSH administrators may decide an appeal.")
        if not resolution.strip():
            raise ValueError("Appeal resolution is required.")
        case = await self._grievance(case_id, company_id)
        self._assert_not_accused(case, actor_id)
        if case.appeal_status != "PENDING":
            raise ValueError("No pending employee appeal.")
        decision = decision.upper()
        if decision not in {"UPHELD", "REJECTED"}:
            raise ValueError("Appeal decision must be UPHELD or REJECTED.")
        case.appeal_status = decision
        case.appeal_resolution = resolution.strip()
        case.appeal_resolved_at = _now()
        case.status = "CLOSED"
        self.session.add(GrievanceCaseEvent(
            id=uuid.uuid4(), case_id=case.id, event_type="APPEAL_DECIDED", actor_id=actor_id,
            event_metadata={"decision": decision},
        ))
        await self.session.commit()
        return case

    async def escalate_overdue(self, *, company_id: uuid.UUID, now: datetime | None = None) -> int:
        now = now or _now()
        cases = (await self.session.execute(select(GrievanceCase).where(
            GrievanceCase.company_id == company_id,
            GrievanceCase.status.in_(["OPEN", "IN_REVIEW", "ESCALATED"]),
        ))).scalars().all()
        count = 0
        for case in cases:
            if _as_utc(case.sla_due_at) < _as_utc(now):
                case.status = "ESCALATED"
                case.escalated_at = now
                case.escalation_level = (case.escalation_level or 0) + 1
                self.session.add(GrievanceCaseEvent(
                    id=uuid.uuid4(), case_id=case.id, event_type="SLA_ESCALATED",
                    event_metadata={"level": case.escalation_level},
                ))
                from app.services import notification_service
                recipients = list((await self.session.execute(select(User.id).where(
                    User.company_id == case.company_id, User.is_active.is_(True),
                    User.role.in_(["admin", "hr_admin", "super_admin"]),
                ).limit(20))).scalars().all())
                if case.investigator_id:
                    recipients.append(case.investigator_id)
                accused = _uuid_set(case.accused_user_ids or [])
                recipients = [recipient for recipient in recipients if recipient not in accused]
                await notification_service.notify(
                    self.session, company_id=case.company_id, recipient_ids=recipients,
                    type="grievance.sla_escalated", category="system", module="grievance",
                    title=f"Confidential grievance SLA escalated: {case.case_number}",
                    body=f"Case {case.case_number} reached escalation level {case.escalation_level}. No complaint details are included in this alert.",
                    link=f"/grievances/cases/{case.id}", priority="high", mandatory=True,
                    entity={"type": "grievance_case", "id": str(case.id)},
                    dedupe_key=f"grievance-escalation:{case.id}:{case.escalation_level}",
                )
                count += 1
        await self.session.commit()
        return count

    # ------------------------------------------------------------------ POSH ICC
    @staticmethod
    def validate_icc_composition(members: Iterable[ICCMember | dict[str, Any]]) -> dict[str, Any]:
        def value(member: ICCMember | dict[str, Any], key: str, default: Any = None) -> Any:
            return member.get(key, default) if isinstance(member, dict) else getattr(member, key, default)

        active = [m for m in members if bool(value(m, "is_active", True))]
        presiding = [m for m in active if str(value(m, "role", "")).upper() == "PRESIDING_OFFICER"]
        women = sum(str(value(m, "gender", "")).upper() in {"FEMALE", "F", "WOMAN"} for m in active)
        external = [m for m in active if bool(value(m, "is_external", False)) or str(value(m, "role", "")).upper() == "EXTERNAL_MEMBER"]
        errors: list[str] = []
        if len(active) < 4:
            errors.append("ICC must have at least four active members.")
        if len(presiding) != 1:
            errors.append("ICC must have exactly one Presiding Officer.")
        elif str(value(presiding[0], "gender", "")).upper() not in {"FEMALE", "F", "WOMAN"}:
            errors.append("The Presiding Officer must be a woman.")
        if not external:
            errors.append("ICC must include an external member.")
        women_percentage = round(women * 100 / len(active), 2) if active else 0.0
        if active and women * 2 < len(active):
            errors.append("At least half of the ICC members must be women.")
        return {
            "valid": not errors, "errors": errors, "member_count": len(active),
            "women_count": women, "women_percentage": women_percentage,
            "external_member_count": len(external),
        }

    async def create_icc_committee(
        self, *, company_id: uuid.UUID, name: str, term_start: date, term_end: date,
        members: list[dict[str, Any]], enforce_composition: bool = True,
    ) -> ICCCommittee:
        if term_end <= term_start:
            raise ValueError("ICC term end must be after its start.")
        composition = self.validate_icc_composition(members)
        if enforce_composition and not composition["valid"]:
            raise ValueError("Invalid ICC composition: " + " ".join(composition["errors"]))
        employee_ids = _uuid_set(item.get("employee_id") for item in members if item.get("employee_id"))
        user_ids = _uuid_set(item.get("user_id") for item in members if item.get("user_id"))
        employees = {row.id: row for row in (await self.session.execute(select(Employee).where(
            Employee.id.in_(employee_ids), Employee.company_id == company_id, Employee.is_deleted.is_(False),
        ))).scalars().all()} if employee_ids else {}
        users = {row.id: row for row in (await self.session.execute(select(User).where(
            User.id.in_(user_ids), User.company_id == company_id, User.is_active.is_(True),
        ))).scalars().all()} if user_ids else {}
        if set(employees) != employee_ids or set(users) != user_ids:
            raise ValueError("Every internal ICC member reference must belong to the committee tenant.")
        for item in members:
            employee_id = _uuid_set([item["employee_id"]]).pop() if item.get("employee_id") else None
            user_id = _uuid_set([item["user_id"]]).pop() if item.get("user_id") else None
            item["employee_id"], item["user_id"] = employee_id, user_id
            if employee_id and user_id and employees[employee_id].user_id != user_id:
                raise ValueError("ICC employee and user references do not match.")
        committee = ICCCommittee(
            id=uuid.uuid4(), company_id=company_id, name=name.strip(),
            term_start=term_start, term_end=term_end, is_active=True,
            validated_at=_now() if composition["valid"] else None,
        )
        self.session.add(committee)
        await self.session.flush()
        for item in members:
            self.session.add(ICCMember(
                id=uuid.uuid4(), committee_id=committee.id,
                user_id=item.get("user_id"), employee_id=item.get("employee_id"),
                name=item["name"], gender=str(item["gender"]).upper(),
                role=str(item["role"]).upper(), is_external=bool(item.get("is_external", False)),
                is_active=bool(item.get("is_active", True)), appointed_at=item.get("appointed_at", term_start),
            ))
        await self.session.commit()
        return await self.get_icc_committee(committee.id, company_id=company_id)

    async def get_icc_committee(self, committee_id: uuid.UUID, *, company_id: uuid.UUID) -> ICCCommittee:
        committee = (await self.session.execute(
            select(ICCCommittee).options(selectinload(ICCCommittee.members)).where(
                ICCCommittee.id == committee_id, ICCCommittee.company_id == company_id,
            )
        )).scalar_one_or_none()
        if committee is None:
            raise LookupError("ICC committee not found.")
        return committee

    async def _posh(self, complaint_id: uuid.UUID, company_id: uuid.UUID) -> POSHComplaint:
        complaint = (await self.session.execute(
            select(POSHComplaint).where(
                POSHComplaint.id == complaint_id, POSHComplaint.company_id == company_id,
            )
        )).scalar_one_or_none()
        if complaint is None:
            raise LookupError("POSH complaint not found.")
        return complaint

    async def create_posh_complaint(
        self, *, company_id: uuid.UUID, committee_id: uuid.UUID, description: str,
        reporter_employee_id: uuid.UUID | None = None, reporter_user_id: uuid.UUID | None = None,
        anonymous: bool = False, accused_user_ids: Iterable[uuid.UUID | str] | None = None,
        filed_at: datetime | None = None,
    ) -> POSHComplaint:
        if not anonymous and reporter_employee_id is None and reporter_user_id is None:
            raise ValueError("A complainant is required unless the complaint is anonymous.")
        if not description.strip():
            raise ValueError("Complaint description is required.")
        if not anonymous:
            await self._validate_reporter(
                company_id=company_id, employee_id=reporter_employee_id, user_id=reporter_user_id,
            )
        committee = await self.get_icc_committee(committee_id, company_id=company_id)
        composition = self.validate_icc_composition(committee.members)
        if not committee.is_active or not composition["valid"]:
            raise ValueError("A complaint requires an active, statutorily composed ICC.")
        filed_at = filed_at or _now()
        if not committee.term_start <= filed_at.date() <= committee.term_end:
            raise ValueError("The ICC term does not cover the complaint filing date.")
        token, token_hash = self._receipt() if anonymous else (None, None)
        complaint = POSHComplaint(
            id=uuid.uuid4(), company_id=company_id,
            complaint_number=f"POSH-{uuid.uuid4().hex[:12].upper()}", committee_id=committee_id,
            reporter_employee_id=None if anonymous else reporter_employee_id,
            reporter_user_id=None if anonymous else reporter_user_id,
            is_anonymous=anonymous, receipt_token_hash=token_hash, description=description.strip(),
            accused_user_ids=[str(v) for v in _uuid_set(accused_user_ids)], status="FILED",
            filed_at=filed_at, inquiry_due_at=filed_at + timedelta(days=90),
        )
        self.session.add(complaint)
        await self.session.commit()
        complaint.receipt_token = token
        return complaint

    @staticmethod
    def serialize_posh(complaint: POSHComplaint, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or _now()
        remaining = _as_utc(complaint.inquiry_due_at) - _as_utc(now)
        return {
            "id": str(complaint.id), "complaint_number": complaint.complaint_number,
            "committee_id": str(complaint.committee_id), "status": complaint.status,
            "is_anonymous": complaint.is_anonymous,
            "reporter_employee_id": None if complaint.is_anonymous else (str(complaint.reporter_employee_id) if complaint.reporter_employee_id else None),
            "reporter_user_id": None if complaint.is_anonymous else (str(complaint.reporter_user_id) if complaint.reporter_user_id else None),
            "description": complaint.description, "filed_at": _iso(complaint.filed_at),
            "inquiry_due_at": _iso(complaint.inquiry_due_at),
            "inquiry_days_remaining": max(0, remaining.days),
            "inquiry_overdue": remaining.total_seconds() < 0 and complaint.status not in {"CLOSED", "CONCILIATED"},
            "conciliation_requested": complaint.conciliation_requested,
            "conciliation_status": complaint.conciliation_status,
            "inquiry_started_at": _iso(complaint.inquiry_started_at),
            "inquiry_completed_at": _iso(complaint.inquiry_completed_at),
            "final_recommendation": complaint.final_recommendation,
            "recommendation_at": _iso(complaint.recommendation_at),
        }

    async def get_posh_complaint(
        self, complaint_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_id: uuid.UUID | None, actor_role: str = "employee",
        receipt_token: str | None = None,
    ) -> POSHComplaint:
        complaint = await self._posh(complaint_id, company_id)
        self._assert_not_accused(complaint, actor_id)
        privileged = actor_role.lower() in {"admin", "hr_admin", "super_admin", "posh_admin"}
        reporter = actor_id is not None and actor_id == complaint.reporter_user_id
        receipt_ok = bool(
            receipt_token and complaint.receipt_token_hash and
            secrets.compare_digest(hashlib.sha256(receipt_token.encode()).hexdigest(), complaint.receipt_token_hash)
        )
        member = (await self.session.execute(select(ICCMember).where(
            ICCMember.committee_id == complaint.committee_id,
            ICCMember.user_id == actor_id, ICCMember.is_active.is_(True),
        ))).scalar_one_or_none() if actor_id else None
        if not (privileged or reporter or receipt_ok or member):
            raise ConfidentialityError("You do not have access to this confidential POSH complaint.")
        return complaint

    async def _assert_posh_worker(
        self, complaint: POSHComplaint, *, actor_id: uuid.UUID, actor_role: str,
    ) -> None:
        """Only POSH/HR administrators or active ICC members may conduct a case."""
        self._assert_not_accused(complaint, actor_id)
        if actor_role.lower() in {"admin", "hr_admin", "super_admin", "posh_admin"}:
            return
        member = (await self.session.execute(select(ICCMember).where(
            ICCMember.committee_id == complaint.committee_id,
            ICCMember.user_id == actor_id, ICCMember.is_active.is_(True),
        ))).scalar_one_or_none()
        if member is None:
            raise ConfidentialityError("Only an active ICC member or POSH administrator may perform this inquiry action.")

    async def record_conciliation(
        self, complaint_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID,
        requested: bool, status_value: str, terms: str | None = None,
        actor_role: str = "employee", receipt_token: str | None = None,
    ) -> POSHComplaint:
        complaint = await self._posh(complaint_id, company_id)
        self._assert_not_accused(complaint, actor_id)
        receipt_ok = bool(
            receipt_token and complaint.receipt_token_hash and
            secrets.compare_digest(hashlib.sha256(receipt_token.encode()).hexdigest(), complaint.receipt_token_hash)
        )
        reporter = (actor_id is not None and actor_id == complaint.reporter_user_id) or receipt_ok
        status_value = status_value.strip().upper()
        if reporter:
            if not requested or status_value not in {"REQUESTED", "PENDING"}:
                raise ConfidentialityError("A complainant may only request conciliation; the ICC records its outcome.")
            if complaint.conciliation_requested:
                raise ValueError("Conciliation has already been requested.")
        else:
            await self._assert_posh_worker(complaint, actor_id=actor_id, actor_role=actor_role)
            if not complaint.conciliation_requested:
                raise ValueError("Conciliation requires a complainant-initiated request.")
            if status_value not in {"REQUESTED", "PENDING", "SETTLED", "COMPLETED", "FAILED", "DECLINED"}:
                raise ValueError("Unsupported conciliation status.")
        if complaint.status == "CONCILIATED":
            raise ValueError("This complaint has already been conciliated.")
        if complaint.inquiry_started_at is not None:
            raise ValueError("Conciliation must occur before a formal inquiry starts.")
        if status_value in {"SETTLED", "COMPLETED"} and not (terms or "").strip():
            raise ValueError("Conciliation settlement terms are required.")
        complaint.conciliation_requested = requested or complaint.conciliation_requested
        complaint.conciliation_status = status_value
        complaint.conciliation_terms = terms.strip() if terms else None
        if status_value in {"SETTLED", "COMPLETED"}:
            complaint.conciliated_at = _now()
            complaint.status = "CONCILIATED"
        elif status_value in {"FAILED", "DECLINED"}:
            complaint.status = "FILED"
        await self.session.commit()
        return complaint

    async def start_posh_inquiry(
        self, complaint_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID,
        actor_role: str = "employee",
    ) -> POSHComplaint:
        complaint = await self._posh(complaint_id, company_id)
        await self._assert_posh_worker(complaint, actor_id=actor_id, actor_role=actor_role)
        if complaint.status == "CONCILIATED":
            raise ValueError("A conciliated complaint cannot enter formal inquiry.")
        if complaint.conciliation_requested and complaint.conciliation_status not in {"FAILED", "DECLINED"}:
            raise ValueError("Resolve or decline conciliation before formal inquiry.")
        complaint.status = "INQUIRY"
        complaint.inquiry_started_at = complaint.inquiry_started_at or _now()
        await self.session.commit()
        return complaint

    async def complete_posh_inquiry(
        self, complaint_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID,
        recommendation: str, actor_role: str = "employee",
    ) -> POSHComplaint:
        complaint = await self._posh(complaint_id, company_id)
        await self._assert_posh_worker(complaint, actor_id=actor_id, actor_role=actor_role)
        if complaint.inquiry_started_at is None:
            raise ValueError("Start the formal inquiry before recording its recommendation.")
        if not recommendation.strip():
            raise ValueError("Final ICC recommendation is required.")
        complaint.final_recommendation = recommendation.strip()
        complaint.recommendation_at = _now()
        complaint.recommendation_by = actor_id
        complaint.inquiry_completed_at = _now()
        complaint.status = "CLOSED"
        await self.session.commit()
        return complaint

    # ------------------------------------------------------------- evidence vault
    @staticmethod
    def _fernet() -> Fernet:
        configured = os.getenv("POSH_EVIDENCE_KEY")
        if configured:
            try:
                return Fernet(configured.encode())
            except (ValueError, TypeError) as exc:
                raise ValueError("POSH_EVIDENCE_KEY must be a valid Fernet key.") from exc
        secret = os.getenv("SECRET_KEY")
        if not secret:
            from app.core.config import settings
            secret = settings.SECRET_KEY.get_secret_value()
        digest = hashlib.sha256(("OFC360-POSH-VAULT-v1:" + secret).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    async def add_evidence(
        self, complaint_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID,
        file_name: str, content_type: str, content: bytes,
        actor_role: str = "employee",
    ) -> POSHEvidence:
        complaint = await self.get_posh_complaint(
            complaint_id, company_id=company_id, actor_id=actor_id, actor_role=actor_role,
        )
        if not content:
            raise ValueError("Evidence content cannot be empty.")
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Evidence exceeds the 10 MB limit.")
        evidence = POSHEvidence(
            id=uuid.uuid4(), complaint_id=complaint.id, file_name=file_name,
            content_type=content_type, ciphertext=self._fernet().encrypt(content),
            sha256=hashlib.sha256(content).hexdigest(), key_version="v1", uploaded_by=actor_id,
        )
        self.session.add(evidence)
        await self.session.commit()
        return evidence

    async def read_evidence(
        self, evidence_id: uuid.UUID, *, company_id: uuid.UUID, actor_id: uuid.UUID,
        actor_role: str = "employee",
    ) -> tuple[bytes, POSHEvidence]:
        evidence = (await self.session.execute(
            select(POSHEvidence).options(selectinload(POSHEvidence.complaint)).where(POSHEvidence.id == evidence_id)
        )).scalar_one_or_none()
        if evidence is None or evidence.complaint.company_id != company_id:
            raise LookupError("Evidence not found.")
        await self.get_posh_complaint(
            evidence.complaint.id, company_id=company_id, actor_id=actor_id, actor_role=actor_role,
        )
        content = self._fernet().decrypt(evidence.ciphertext)
        if not secrets.compare_digest(hashlib.sha256(content).hexdigest(), evidence.sha256):
            raise ValueError("Evidence integrity verification failed.")
        return content, evidence

    async def record_training(
        self, *, company_id: uuid.UUID, audience: str, training_title: str,
        completed_at: datetime, employee_id: uuid.UUID | None = None,
        icc_member_id: uuid.UUID | None = None, provider: str | None = None,
        valid_until: date | None = None, score: int | None = None,
        certificate_reference: str | None = None,
    ) -> POSHTrainingRecord:
        audience = audience.upper()
        if audience not in {"EMPLOYEE", "ICC"}:
            raise ValueError("Training audience must be EMPLOYEE or ICC.")
        if audience == "EMPLOYEE" and employee_id is None:
            raise ValueError("Employee training requires employee_id.")
        if audience == "ICC" and icc_member_id is None:
            raise ValueError("ICC training requires icc_member_id.")
        employee = None
        if employee_id is not None:
            employee = (await self.session.execute(select(Employee).where(
                Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted.is_(False),
            ))).scalar_one_or_none()
            if employee is None:
                raise ValueError("Training employee must belong to the training tenant.")
        if icc_member_id is not None:
            member = (await self.session.execute(select(ICCMember).options(
                selectinload(ICCMember.committee),
            ).where(ICCMember.id == icc_member_id))).scalar_one_or_none()
            if member is None or member.committee.company_id != company_id:
                raise ValueError("ICC member must belong to the training tenant.")
            if employee is not None and member.employee_id not in {None, employee.id}:
                raise ValueError("Training employee and ICC member references do not match.")
        record = POSHTrainingRecord(
            id=uuid.uuid4(), company_id=company_id, employee_id=employee_id,
            icc_member_id=icc_member_id, audience=audience, training_title=training_title,
            provider=provider, completed_at=completed_at, valid_until=valid_until,
            score=score, certificate_reference=certificate_reference,
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def generate_annual_return(
        self, *, company_id: uuid.UUID, return_year: int, actor_id: uuid.UUID,
    ) -> POSHAnnualReturn:
        start, end = datetime(return_year, 1, 1, tzinfo=UTC), datetime(return_year + 1, 1, 1, tzinfo=UTC)
        complaints = (await self.session.execute(select(POSHComplaint).where(
            POSHComplaint.company_id == company_id,
            POSHComplaint.filed_at >= start, POSHComplaint.filed_at < end,
        ))).scalars().all()
        closed = [c for c in complaints if c.status in {"CLOSED", "CONCILIATED"}]
        overdue = [c for c in complaints if c.status not in {"CLOSED", "CONCILIATED"} and _as_utc(c.inquiry_due_at) < end]
        trainings = (await self.session.execute(select(POSHTrainingRecord).where(
            POSHTrainingRecord.company_id == company_id,
            POSHTrainingRecord.completed_at >= start, POSHTrainingRecord.completed_at < end,
        ))).scalars().all()
        section_21 = {
            "calendar_year": return_year,
            "complaints_received": len(complaints),
            "complaints_disposed": len(closed),
            "complaints_pending_over_90_days": len(overdue),
            "employee_awareness_training_records": sum(t.audience == "EMPLOYEE" for t in trainings),
            "icc_training_records": sum(t.audience == "ICC" for t in trainings),
        }
        section_22 = {
            "calendar_year": return_year, "cases_filed": len(complaints),
            "cases_disposed": len(closed), "cases_pending": len(complaints) - len(closed),
        }
        existing = (await self.session.execute(select(POSHAnnualReturn).where(
            POSHAnnualReturn.company_id == company_id, POSHAnnualReturn.return_year == return_year,
        ))).scalar_one_or_none()
        annual = existing or POSHAnnualReturn(id=uuid.uuid4(), company_id=company_id, return_year=return_year)
        annual.section_21 = section_21
        annual.section_22 = section_22
        annual.generated_by = actor_id
        annual.generated_at = _now()
        self.session.add(annual)
        await self.session.commit()
        return annual
