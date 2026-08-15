"""Employee repository: all async database operations, no business logic."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.asset import Asset
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.employee_document import EmployeeDocument
from app.models.employee_education import EmployeeEducation
from app.models.employee_emergency_contact import EmployeeEmergencyContact
from app.models.employee_experience import EmployeeExperience
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee_onboarding import EmployeeOnboarding
from app.models.employee_skill import EmployeeSkill

logger = logging.getLogger(__name__)

# Default onboarding steps seeded on employee creation
DEFAULT_ONBOARDING_STEPS = [
    {"step_name": "PERSONAL_INFO", "step_order": 1, "is_required": True},
    {"step_name": "BANK_DETAILS", "step_order": 2, "is_required": True},
    {"step_name": "EMERGENCY_CONTACT", "step_order": 3, "is_required": True},
    {"step_name": "DOCUMENT_UPLOAD", "step_order": 4, "is_required": True},
    {"step_name": "EDUCATION", "step_order": 5, "is_required": False},
    {"step_name": "EXPERIENCE", "step_order": 6, "is_required": False},
]


class EmployeeRepository:
    """Data access layer for all employee-related tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _active_filter(self):
        """Return is_deleted=False filter."""
        return Employee.is_deleted == False  # noqa: E712

    def _with_relations(self):
        """Eager-load all relations using selectinload."""
        return [
            selectinload(Employee.addresses),
            selectinload(Employee.documents),
            selectinload(Employee.education),
            selectinload(Employee.experience),
            selectinload(Employee.skills),
            selectinload(Employee.assets),
            selectinload(Employee.emergency_contacts),
            selectinload(Employee.bank_accounts),
            selectinload(Employee.leave_policies),
            selectinload(Employee.onboarding_steps),
        ]

    # ------------------------------------------------------------------
    # Employee CRUD
    # ------------------------------------------------------------------

    async def create_employee(self, **kwargs: Any) -> Employee:
        """Insert a new employee record."""
        employee = Employee(**kwargs)
        self.session.add(employee)
        await self.session.flush()  # get id without committing
        return employee

    async def get_by_id(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> Employee | None:
        """Return employee with all relations, or None if not found. Strictly enforces company_id when provided."""
        stmt = select(Employee).where(and_(Employee.id == employee_uuid, self._active_filter()))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        result = await self.session.execute(
            stmt.options(*self._with_relations())
        )
        return result.scalar_one_or_none()

    async def get_by_id_raw(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> Employee | None:
        """Return employee without eager-loading relations (lightweight). Strictly enforces company_id when provided."""
        stmt = select(Employee).where(Employee.id == employee_uuid)
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_employee_id(self, employee_id: str, company_id: uuid.UUID | None = None) -> Employee | None:
        """Look up by string employee_id (e.g. EMP-202606-0001). Strictly enforces company_id when provided."""
        stmt = select(Employee).where(and_(Employee.employee_id == employee_id, self._active_filter()))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        else:
            stmt = stmt.execution_options(bypass_tenant=True)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_personal_email(self, email: str) -> Employee | None:
        """Check for duplicate personal email (excludes deleted) — cross-company."""
        result = await self.session.execute(
            select(Employee)
            .where(and_(Employee.personal_email == email.lower(), self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_personal_email_in_company(self, email: str, company_id) -> Employee | None:
        """Check for duplicate personal email within a specific company (excludes deleted)."""
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    Employee.personal_email == email.lower(),
                    Employee.company_id == company_id,
                    self._active_filter(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Employee | None:
        """Check for duplicate phone (excludes deleted) — cross-company."""
        result = await self.session.execute(
            select(Employee)
            .where(and_(Employee.phone == phone, self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_phone_in_company(self, phone: str, company_id) -> Employee | None:
        """Check for duplicate phone within a specific company (excludes deleted)."""
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    Employee.phone == phone,
                    Employee.company_id == company_id,
                    self._active_filter(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_company_email(self, email: str) -> Employee | None:
        """Check for duplicate company email (excludes deleted) — cross-company."""
        result = await self.session.execute(
            select(Employee)
            .where(and_(Employee.company_email == email.lower(), self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_company_email_in_company(self, email: str, company_id) -> Employee | None:
        """Check for duplicate company email within a specific company (excludes deleted)."""
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    Employee.company_email == email.lower(),
                    Employee.company_id == company_id,
                    self._active_filter(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_employee_id_in_company(self, employee_id: str, company_id) -> Employee | None:
        """Look up by string employee_id within a specific company."""
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    Employee.employee_id == employee_id,
                    Employee.company_id == company_id,
                    self._active_filter(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_activation_token(self, token: str) -> Employee | None:
        """Look up employee by activation token (includes deleted filter)."""
        result = await self.session.execute(
            select(Employee).where(Employee.activation_token == token)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID, company_id: uuid.UUID | None = None) -> Employee | None:
        """Look up employee by linked user_id. Strictly enforces company_id when provided."""
        stmt = select(Employee).where(and_(Employee.user_id == user_id, self._active_filter()))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_employees(
        self,
        company_id: uuid.UUID | None = None,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        designation: str | None = None,
        shift: str | None = None,
        sort: str | None = None,
        order: str | None = "asc",
    ) -> list[Employee]:
        """Return paginated, filtered, sorted list of employees strictly scoped to company_id (no relations loaded)."""
        filters = [self._active_filter()]
        if company_id is not None:
            filters.append(Employee.company_id == company_id)

        stmt = select(Employee).where(and_(*filters))

        if department and department.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.department == department)
        if status and status.lower() not in {"", "all"}:
            norm_status = status.strip().upper().replace(" ", "_")
            stmt = stmt.where(
                or_(
                    Employee.status.ilike(f"%{status.strip()}%"),
                    Employee.status == norm_status,
                    Employee.employment_status == norm_status,
                )
            )
        if employment_type and employment_type.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.employment_type == employment_type.upper())
        if designation and designation.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.designation == designation)
        if shift and shift.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.shift == shift)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Employee.employee_id.ilike(pattern),
                    Employee.personal_email.ilike(pattern),
                    Employee.company_email.ilike(pattern),
                    Employee.cost_center_id.ilike(pattern),
                )
            )

        # Sorting logic
        sort_mapping = {
            "joined_date": Employee.joining_date,
            "joining_date": Employee.joining_date,
            "employee_id": Employee.employee_id,
            "department": Employee.department,
            "designation": Employee.designation,
            "shift": Employee.shift,
            "status": Employee.status,
            "employee_capacity": Employee.employee_capacity,
            "cost_center_id": Employee.cost_center_id,
            "created_at": Employee.created_at,
        }

        if sort == "name":
            if order == "desc":
                sort_exprs = [Employee.first_name.desc(), Employee.last_name.desc()]
            else:
                sort_exprs = [Employee.first_name.asc(), Employee.last_name.asc()]
        elif sort in sort_mapping:
            col = sort_mapping[sort]
            if order == "desc":
                sort_exprs = [col.desc()]
            else:
                sort_exprs = [col.asc()]
        else:
            sort_exprs = [Employee.created_at.desc()]

        stmt = stmt.order_by(*sort_exprs).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_employees(
        self,
        company_id: uuid.UUID | None = None,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
        designation: str | None = None,
        shift: str | None = None,
    ) -> int:
        """Count total employees matching filters within a company (for pagination)."""
        filters = [self._active_filter()]
        if company_id is not None:
            filters.append(Employee.company_id == company_id)

        stmt = select(func.count()).select_from(Employee).where(and_(*filters))

        if department and department.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.department == department)
        if status and status.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.status == status.upper())
        if employment_type and employment_type.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.employment_type == employment_type.upper())
        if designation and designation.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.designation == designation)
        if shift and shift.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.shift == shift)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Employee.employee_id.ilike(pattern),
                    Employee.personal_email.ilike(pattern),
                    Employee.company_email.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_employee(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None, **kwargs: Any) -> None:
        """Partial update of employee fields strictly scoped to company_id when provided."""
        stmt = update(Employee).where(Employee.id == employee_uuid)
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        await self.session.execute(stmt.values(**kwargs))

    async def soft_delete(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None, deleted_by: uuid.UUID | None = None) -> None:
        """Mark employee as deleted (soft delete) and release unique fields strictly scoped to company_id when provided."""
        stmt = select(Employee).where(Employee.id == employee_uuid)
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        result = await self.session.execute(stmt)
        employee = result.scalar_one_or_none()
        if employee:
            import uuid as py_uuid
            # Scramble unique fields
            new_email = f"del_{py_uuid.uuid4().hex[:8]}_{employee.personal_email}"
            if len(new_email) > 255:
                new_email = new_email[:255]
            
            new_emp_id = f"del_{py_uuid.uuid4().hex[:4]}_{employee.employee_id}"
            if len(new_emp_id) > 20:
                new_emp_id = new_emp_id[:20]
                
            new_phone = py_uuid.uuid4().hex[:15]
            
            employee.is_deleted = True
            employee.deleted_at = datetime.now(timezone.utc)
            employee.personal_email = new_email
            employee.employee_id = new_emp_id
            employee.phone = new_phone
            employee.status = "DELETED"
            await self.session.flush()

    async def update_status(self, employee_uuid: uuid.UUID, status: str, company_id: uuid.UUID | None = None) -> None:
        """Update the employee lifecycle status strictly scoped to company_id when provided."""
        stmt = update(Employee).where(Employee.id == employee_uuid)
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        await self.session.execute(stmt.values(status=status))

    # ------------------------------------------------------------------
    # Address
    # ------------------------------------------------------------------

    async def upsert_address(self, employee_uuid: uuid.UUID, address_type: str, data: dict) -> EmployeeAddress:
        """Insert or update an address by (employee_id, address_type)."""
        result = await self.session.execute(
            select(EmployeeAddress).where(
                and_(
                    EmployeeAddress.employee_id == employee_uuid,
                    EmployeeAddress.address_type == address_type,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            return existing
        addr = EmployeeAddress(employee_id=employee_uuid, address_type=address_type, **data)
        self.session.add(addr)
        await self.session.flush()
        return addr

    # ------------------------------------------------------------------
    # Generic child record creators
    # ------------------------------------------------------------------

    async def create_document(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeDocument:
        obj = EmployeeDocument(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_education(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeEducation:
        obj = EmployeeEducation(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_experience(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeExperience:
        obj = EmployeeExperience(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_skill(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeSkill:
        obj = EmployeeSkill(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_emergency_contact(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeEmergencyContact:
        obj = EmployeeEmergencyContact(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_bank_account(self, employee_uuid: uuid.UUID, data: dict) -> EmployeeBankAccount:
        obj = EmployeeBankAccount(employee_id=employee_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------

    async def create_onboarding_steps(self, employee_uuid: uuid.UUID) -> list[EmployeeOnboarding]:
        """Seed default onboarding checklist for a new employee."""
        steps = []
        for step_def in DEFAULT_ONBOARDING_STEPS:
            step = EmployeeOnboarding(employee_id=employee_uuid, **step_def)
            self.session.add(step)
            steps.append(step)
        await self.session.flush()
        return steps

    async def get_onboarding_steps(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> list[EmployeeOnboarding]:
        """Return all onboarding steps for an employee ordered by step_order, scoped to company_id when provided."""
        stmt = select(EmployeeOnboarding).where(EmployeeOnboarding.employee_id == employee_uuid)
        if company_id is not None:
            stmt = stmt.join(Employee, EmployeeOnboarding.employee_id == Employee.id).where(Employee.company_id == company_id)
        result = await self.session.execute(
            stmt.order_by(EmployeeOnboarding.step_order)
        )
        return list(result.scalars().all())

    async def complete_onboarding_step(self, step_id: uuid.UUID) -> EmployeeOnboarding | None:
        """Mark an onboarding step as completed."""
        result = await self.session.execute(
            select(EmployeeOnboarding).where(EmployeeOnboarding.id == step_id)
        )
        step = result.scalar_one_or_none()
        if step:
            step.is_completed = True
            step.status = "VERIFIED"
            step.completed_at = datetime.now(timezone.utc)
        return step
