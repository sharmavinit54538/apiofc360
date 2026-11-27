"""Employee repository: all async database operations, no business logic."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

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

    def _with_relations(self, include_sensitive_pii: bool = True):
        """Eager-load employee relations using selectinload while protecting manager PII."""
        rels = [
            selectinload(Employee.addresses),
            selectinload(Employee.documents),
            selectinload(Employee.education),
            selectinload(Employee.experience),
            selectinload(Employee.skills),
            selectinload(Employee.assets),
            selectinload(Employee.emergency_contacts),
            selectinload(Employee.leave_policies),
            selectinload(Employee.onboarding_steps),
            selectinload(Employee.reporting_manager).load_only(
                Employee.id, Employee.first_name, Employee.last_name, Employee.employee_id
            ),
            selectinload(Employee.manager).load_only(
                Employee.id, Employee.first_name, Employee.last_name, Employee.employee_id
            ),
        ]
        if include_sensitive_pii:
            rels.append(selectinload(Employee.bank_accounts))
        return rels

    # ------------------------------------------------------------------
    # Employee CRUD
    # ------------------------------------------------------------------

    async def create_employee(self, **kwargs: Any) -> Employee:
        """Insert a new employee record."""
        employee = Employee(**kwargs)
        self.session.add(employee)
        await self.session.flush()  # get id without committing
        return employee

    _SAFE_DETAIL_LOAD_COLUMNS = (
        Employee.id,
        Employee.user_id,
        Employee.company_id,
        Employee.employee_id,
        Employee.first_name,
        Employee.last_name,
        Employee.profile_photo_url,
        Employee.gender,
        Employee.date_of_birth,
        Employee.personal_email,
        Employee.company_email,
        Employee.phone,
        Employee.alternate_phone,
        Employee.blood_group,
        Employee.marital_status,
        Employee.middle_name,
        Employee.father_name,
        Employee.mother_name,
        Employee.spouse_name,
        Employee.nationality,
        Employee.preferred_language,
        Employee.tax_regime,
        Employee.work_mode,
        Employee.business_unit,
        Employee.employee_category,
        Employee.probation_period_months,
        Employee.onboarding_data,
        Employee.employee_onboarding_completed,
        Employee.employee_onboarding_step,
        Employee.is_face_enrolled,
        Employee.face_enrolled_at,
        Employee.department,
        Employee.designation,
        Employee.team,
        Employee.reporting_manager_id,
        Employee.manager_id,
        Employee.branch,
        Employee.branch_id,
        Employee.legal_entity_id,
        Employee.work_location,
        Employee.employment_type,
        Employee.employment_status,
        Employee.joining_date,
        Employee.last_promotion_date,
        Employee.probation_end_date,
        Employee.shift,
        Employee.shift_id,
        Employee.employee_capacity,
        Employee.cost_center_id,
        Employee.ctc,
        Employee.basic_salary,
        Employee.hra,
        Employee.bonus,
        Employee.pf,
        Employee.esi,
        Employee.professional_tax,
        Employee.role,
        Employee.leave_group,
        Employee.status,
        Employee.role_metadata,
        Employee.verification_status,
        Employee.is_active,
        Employee.deactivated_at,
        Employee.deactivated_by,
        Employee.deactivation_reason,
        Employee.activation_token_expires_at,
        Employee.invited_at,
        Employee.invited_by,
        Employee.is_deleted,
        Employee.deleted_at,
        Employee.created_by,
        Employee.created_at,
        Employee.updated_at,
        Employee.department_id,
    )

    async def get_by_id(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        *,
        include_sensitive_pii: bool = True,
    ) -> Employee | None:
        """Return employee with relations, strictly enforcing company_id when provided."""
        stmt = select(Employee).where(and_(Employee.id == employee_uuid, self._active_filter()))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        options = list(self._with_relations(include_sensitive_pii=include_sensitive_pii))
        if not include_sensitive_pii:
            options.append(load_only(*self._SAFE_DETAIL_LOAD_COLUMNS))
        result = await self.session.execute(stmt.options(*options))
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
        norm_email = email.strip().lower()
        result = await self.session.execute(
            select(Employee)
            .where(and_(func.lower(Employee.personal_email) == norm_email, self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_any_by_personal_email(self, email: str) -> Employee | None:
        """Check for any employee row holding personal_email (including soft-deleted) — cross-company."""
        norm_email = email.strip().lower()
        result = await self.session.execute(
            select(Employee)
            .options(load_only(Employee.id, Employee.company_id, Employee.user_id, Employee.personal_email, Employee.is_deleted))
            .where(func.lower(Employee.personal_email) == norm_email)
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_personal_email_in_company(self, email: str, company_id) -> Employee | None:
        """Check for duplicate personal email within a specific company (excludes deleted)."""
        norm_email = email.strip().lower()
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    func.lower(Employee.personal_email) == norm_email,
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
        norm_email = email.strip().lower()
        result = await self.session.execute(
            select(Employee)
            .where(and_(func.lower(Employee.company_email) == norm_email, self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_company_email_in_company(self, email: str, company_id) -> Employee | None:
        """Check for duplicate company email within a specific company (excludes deleted)."""
        norm_email = email.strip().lower()
        result = await self.session.execute(
            select(Employee).where(
                and_(
                    func.lower(Employee.company_email) == norm_email,
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

    _LIST_LOAD_COLUMNS = (
        Employee.id,
        Employee.company_id,
        Employee.user_id,
        Employee.employee_id,
        Employee.first_name,
        Employee.last_name,
        Employee.profile_photo_url,
        Employee.company_email,
        Employee.personal_email,
        Employee.phone,
        Employee.department,
        Employee.designation,
        Employee.employment_type,
        Employee.employment_status,
        Employee.shift,
        Employee.employee_capacity,
        Employee.cost_center_id,
        Employee.reporting_manager_id,
        Employee.manager_id,
        Employee.status,
        Employee.joining_date,
        Employee.created_at,
        Employee.activation_token,
        Employee.activation_token_expires_at,
        Employee.role,
        Employee.is_active,
        Employee.deactivated_at,
        Employee.deactivated_by,
        Employee.deactivation_reason,
        Employee.role_metadata,
        Employee.verification_status,
        Employee.is_deleted,
    )

    def _apply_list_filters(
        self,
        stmt,
        *,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
        designation: str | None = None,
        shift: str | None = None,
        role: str | None = None,
        allowed_employee_ids: list[uuid.UUID] | None = None,
    ):
        """Apply common directory filters consistently across list and count queries."""
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                stmt = stmt.where(Employee.id.in_([]))
            else:
                stmt = stmt.where(Employee.id.in_(allowed_employee_ids))
        if department and department.strip().lower() not in {"", "all"}:
            stmt = stmt.where(func.lower(func.trim(Employee.department)) == department.strip().lower())
        if status and status.strip().lower() not in {"", "all"}:
            norm_status = status.strip().upper().replace(" ", "_")
            if norm_status == "INACTIVE":
                stmt = stmt.where(
                    or_(
                        func.upper(Employee.status).in_(["INACTIVE", "DISABLED", "DEACTIVATED"]),
                        func.upper(Employee.employment_status) == "INACTIVE",
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        func.upper(Employee.status) == norm_status,
                        func.upper(Employee.employment_status) == norm_status,
                    )
                )
        if employment_type and employment_type.strip().lower() not in {"", "all"}:
            stmt = stmt.where(func.upper(Employee.employment_type) == employment_type.strip().upper())
        if designation and designation.strip().lower() not in {"", "all"}:
            stmt = stmt.where(func.lower(func.trim(Employee.designation)) == designation.strip().lower())
        if shift and shift.strip().lower() not in {"", "all"}:
            stmt = stmt.where(func.lower(func.trim(Employee.shift)) == shift.strip().lower())
        if role and role.strip().lower() not in {"", "all"}:
            stmt = stmt.where(func.lower(Employee.role) == role.strip().lower())
        cleaned_search = search.strip() if isinstance(search, str) else ""
        if cleaned_search:
            pattern = f"%{cleaned_search}%"
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    (
                        func.coalesce(Employee.first_name, "")
                        + " "
                        + func.coalesce(Employee.last_name, "")
                    ).ilike(pattern),
                    Employee.employee_id.ilike(pattern),
                    Employee.personal_email.ilike(pattern),
                    Employee.company_email.ilike(pattern),
                    Employee.department.ilike(pattern),
                    Employee.designation.ilike(pattern),
                    Employee.role.ilike(pattern),
                    Employee.cost_center_id.ilike(pattern),
                )
            )
        return stmt

    @staticmethod
    def _build_sort_exprs(sort: str | None, order: str | None):
        sort_mapping = {
            "joined_date": Employee.joining_date,
            "joining_date": Employee.joining_date,
            "employee_id": Employee.employee_id,
            "department": Employee.department,
            "designation": Employee.designation,
            "role": Employee.role,
            "shift": Employee.shift,
            "status": Employee.status,
            "employee_capacity": Employee.employee_capacity,
            "cost_center_id": Employee.cost_center_id,
            "created_at": Employee.created_at,
        }
        order_desc = (order or "asc").strip().lower() == "desc"
        sort_key = (sort or "").strip().lower()
        if sort_key == "name":
            if order_desc:
                return [Employee.first_name.desc(), Employee.last_name.desc(), Employee.id.asc()]
            return [Employee.first_name.asc(), Employee.last_name.asc(), Employee.id.asc()]
        if sort_key in sort_mapping:
            col = sort_mapping[sort_key]
            if order_desc:
                return [col.desc(), Employee.id.asc()]
            return [col.asc(), Employee.id.asc()]
        return [Employee.created_at.desc(), Employee.id.asc()]

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
        role: str | None = None,
        sort: str | None = None,
        order: str | None = "asc",
        include_sensitive_pii: bool = False,
        allowed_employee_ids: list[uuid.UUID] | None = None,
    ) -> list[Employee]:
        """Return paginated, filtered, sorted list of employees strictly scoped to company_id."""
        filters = [self._active_filter()]
        if company_id is not None:
            filters.append(Employee.company_id == company_id)

        stmt = select(Employee).where(and_(*filters))
        if not include_sensitive_pii:
            stmt = stmt.options(load_only(*self._LIST_LOAD_COLUMNS))

        stmt = self._apply_list_filters(
            stmt,
            department=department,
            status=status,
            employment_type=employment_type,
            search=search,
            designation=designation,
            shift=shift,
            role=role,
            allowed_employee_ids=allowed_employee_ids,
        )
        stmt = stmt.order_by(*self._build_sort_exprs(sort, order)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_and_count_employees(
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
        role: str | None = None,
        sort: str | None = None,
        order: str | None = "asc",
        include_sensitive_pii: bool = False,
        allowed_employee_ids: list[uuid.UUID] | None = None,
    ) -> tuple[list[Employee], int]:
        """Fetch paginated employee rows and total count in a single SQL window query."""
        filters = [self._active_filter()]
        if company_id is not None:
            filters.append(Employee.company_id == company_id)

        total_col = func.count(Employee.id).over().label("_total_count")
        stmt = select(Employee, total_col).where(and_(*filters))
        if not include_sensitive_pii:
            stmt = stmt.options(
                load_only(*self._LIST_LOAD_COLUMNS),
                selectinload(Employee.reporting_manager).load_only(
                    Employee.id, Employee.first_name, Employee.last_name, Employee.employee_id
                ),
            )

        stmt = self._apply_list_filters(
            stmt,
            department=department,
            status=status,
            employment_type=employment_type,
            search=search,
            designation=designation,
            shift=shift,
            role=role,
            allowed_employee_ids=allowed_employee_ids,
        )
        stmt = stmt.order_by(*self._build_sort_exprs(sort, order)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        rows = result.all()
        if not rows:
            if offset > 0:
                total = await self.count_employees(
                    company_id=company_id,
                    department=department,
                    status=status,
                    employment_type=employment_type,
                    search=search,
                    designation=designation,
                    shift=shift,
                    role=role,
                    allowed_employee_ids=allowed_employee_ids,
                )
                return [], total
            return [], 0
        employees = [r[0] for r in rows]
        total = int(rows[0][1] or 0)
        return employees, total

    async def count_employees(
        self,
        company_id: uuid.UUID | None = None,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
        designation: str | None = None,
        shift: str | None = None,
        role: str | None = None,
        allowed_employee_ids: list[uuid.UUID] | None = None,
    ) -> int:
        """Count total employees matching filters within a company (for pagination)."""
        filters = [self._active_filter()]
        if company_id is not None:
            filters.append(Employee.company_id == company_id)

        stmt = select(func.count()).select_from(Employee).where(and_(*filters))
        stmt = self._apply_list_filters(
            stmt,
            department=department,
            status=status,
            employment_type=employment_type,
            search=search,
            designation=designation,
            shift=shift,
            role=role,
            allowed_employee_ids=allowed_employee_ids,
        )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_employee(self, employee_uuid: uuid.UUID, company_id: uuid.UUID | None = None, **kwargs: Any) -> None:
        """Partial update of employee fields strictly scoped to company_id when provided."""
        pii_fields = {"aadhaar_number", "pan_number", "uan_number", "passport_number", "voter_id"}
        changed_pii = pii_fields.intersection(kwargs)
        if changed_pii:
            from app.core.field_encryption import hmac_sha256_blind_index

            if company_id is None:
                company_result = await self.session.execute(
                    select(Employee.company_id)
                    .where(Employee.id == employee_uuid)
                    .execution_options(bypass_tenant=True)
                )
                company_id = company_result.scalar_one_or_none()
            for field_name in changed_pii:
                kwargs[f"{field_name}_blind_idx"] = hmac_sha256_blind_index(
                    kwargs[field_name], company_id
                )

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
            
            # Detach reporting references from active subordinates so hierarchy isn't left dangling
            await self.session.execute(
                update(Employee)
                .where(
                    Employee.company_id == employee.company_id,
                    or_(
                        Employee.reporting_manager_id == employee_uuid,
                        Employee.manager_id == employee_uuid,
                    ),
                )
                .values(reporting_manager_id=None, manager_id=None)
            )
            employee.is_deleted = True
            employee.is_active = False
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
