"""Department repository layer: direct database operations for the Department module."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User

logger = logging.getLogger(__name__)


class DepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active_filter(self):
        return Department.is_deleted == False  # noqa: E712

    async def create_department(self, **kwargs: Any) -> Department:
        department = Department(**kwargs)
        self.session.add(department)
        await self.session.flush()
        return department

    async def get_by_id(self, department_uuid: uuid.UUID) -> Department | None:
        result = await self.session.execute(
            select(Department)
            .where(and_(Department.id == department_uuid, self._active_filter()))
            .options(
                selectinload(Department.manager_user),
                selectinload(Department.creator),
                selectinload(Department.parent_department),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_raw(self, department_uuid: uuid.UUID) -> Department | None:
        result = await self.session.execute(
            select(Department).where(Department.id == department_uuid)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Department | None:
        result = await self.session.execute(
            select(Department)
            .where(and_(func.lower(Department.department_name) == name.lower(), self._active_filter()))
        )
        return result.scalar_one_or_none()

    async def get_by_name_all(self, name: str) -> Department | None:
        result = await self.session.execute(
            select(Department)
            .where(func.lower(Department.department_name) == name.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Department | None:
        result = await self.session.execute(
            select(Department)
            .where(and_(Department.department_code == code.upper(), self._active_filter()))
        )
        return result.scalar_one_or_none()

    async def list_departments(
        self,
        status: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Department]:
        stmt = select(Department).where(self._active_filter()).options(
            selectinload(Department.parent_department),
            selectinload(Department.manager_user),
        )

        if status and status.lower() != "all":
            stmt = stmt.where(Department.status == status.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Department.department_name.ilike(pattern),
                    Department.department_code.ilike(pattern),
                )
            )

        sort_column = Department.created_at.desc()
        if sort_by:
            s_by = sort_by.lower()
            if s_by in {"department_name", "name"}:
                col = Department.department_name
            elif s_by in {"department_code", "code"}:
                col = Department.department_code
            elif s_by == "status":
                col = Department.status
            elif s_by in {"created_at", "created_date", "createddate"}:
                col = Department.created_at
            else:
                col = Department.created_at

            sort_column = col.asc() if sort_order and sort_order.lower() == "asc" else col.desc()

        stmt = stmt.order_by(sort_column).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        if not items:
            fallback_res = await self.session.execute(stmt.execution_options(bypass_tenant=True))
            items = list(fallback_res.scalars().all())

        return items

    async def count_departments(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Department).where(self._active_filter())

        if status and status.lower() != "all":
            stmt = stmt.where(Department.status == status.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Department.department_name.ilike(pattern),
                    Department.department_code.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        count = result.scalar_one()

        if count == 0:
            fallback_res = await self.session.execute(stmt.execution_options(bypass_tenant=True))
            count = fallback_res.scalar_one()

        return count

    async def update_department(self, department_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Department).where(Department.id == department_uuid).values(**kwargs)
        )

    async def soft_delete(self, department_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(Department)
            .where(Department.id == department_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # Employee count helpers
    # ------------------------------------------------------------------

    async def get_employee_count(self, department_uuid: uuid.UUID, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Employee).where(
            and_(Employee.department_id == department_uuid, Employee.is_deleted == False)  # noqa: E712
        )
        if active_only:
            stmt = stmt.where(Employee.status == "ACTIVE")
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def get_inactive_employee_count(self, department_uuid: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Employee).where(
            and_(
                Employee.department_id == department_uuid,
                Employee.is_deleted == False,  # noqa: E712
                Employee.status != "ACTIVE",
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    # ------------------------------------------------------------------
    # Assign / Remove Manager / Employee
    # ------------------------------------------------------------------

    async def assign_manager(self, department_uuid: uuid.UUID, manager_user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Department)
            .where(Department.id == department_uuid)
            .values(manager_id=manager_user_id)
        )

    async def remove_manager(self, department_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(Department)
            .where(Department.id == department_uuid)
            .values(manager_id=None)
        )

    async def get_manager_by_user_id(self, user_id: uuid.UUID) -> User | None:
        from app.models.user import User, UserRole
        from app.models.manager import Manager
        from app.models.employee import Employee
        from sqlalchemy import select

        # 1. Try resolving directly as a User
        allowed_roles = {"super_admin", "hr_admin", "manager", "executive", "it_admin"}
        result = await self.session.execute(
            select(User).where(and_(User.id == user_id, User.role.in_(allowed_roles)))
        )
        user = result.scalar_one_or_none()
        if user:
            return user

        # 2. Check if user_id is a Manager ID (Manager.id)
        result = await self.session.execute(
            select(Manager).where(Manager.id == user_id)
        )
        manager = result.scalar_one_or_none()
        if manager:
            if manager.user_id:
                result = await self.session.execute(
                    select(User).where(and_(User.id == manager.user_id, User.role.in_(allowed_roles)))
                )
                user = result.scalar_one_or_none()
                if user:
                    return user
            else:
                # Check if a user with this manager's email already exists
                manager_email = manager.company_email.lower() if manager.company_email else manager.personal_email.lower()
                result = await self.session.execute(
                    select(User).where(User.email == manager_email)
                )
                existing_user = result.scalar_one_or_none()
                if existing_user:
                    manager.user_id = existing_user.id
                    self.session.add(manager)
                    await self.session.flush()
                    return existing_user

                # Auto-create pending user for this manager
                new_user_id = uuid.uuid4()
                user = User(
                    id=new_user_id,
                    company_id=manager.company_id,
                    name=f"{manager.first_name} {manager.last_name}".strip(),
                    email=manager_email,
                    phone=manager.phone[:10] if manager.phone else None,
                    password_hash="!",  # Unusable hash until activation
                    is_active=False,
                    is_verified=False,
                    role=UserRole.MANAGER,
                )
                self.session.add(user)
                manager.user_id = new_user_id
                self.session.add(manager)
                await self.session.flush()
                return user

        # 3. Check if user_id is an Employee ID (Employee.id)
        result = await self.session.execute(
            select(Employee).where(Employee.id == user_id)
        )
        employee = result.scalar_one_or_none()
        if employee:
            if employee.user_id:
                result = await self.session.execute(
                    select(User).where(and_(User.id == employee.user_id, User.role.in_(allowed_roles)))
                )
                user = result.scalar_one_or_none()
                if user:
                    return user
            else:
                # Check if a user with this employee's email already exists
                employee_email = employee.company_email.lower() if employee.company_email else employee.personal_email.lower()
                result = await self.session.execute(
                    select(User).where(User.email == employee_email)
                )
                existing_user = result.scalar_one_or_none()
                if existing_user:
                    employee.user_id = existing_user.id
                    self.session.add(employee)
                    await self.session.flush()
                    return existing_user

                # Auto-create pending user for this employee
                new_user_id = uuid.uuid4()
                emp_role = UserRole.EMPLOYEE
                if employee.role and employee.role.lower() in allowed_roles:
                    emp_role = employee.role.lower()
                user = User(
                    id=new_user_id,
                    company_id=employee.company_id,
                    name=f"{employee.first_name} {employee.last_name}".strip(),
                    email=employee_email,
                    phone=employee.phone[:10] if employee.phone else None,
                    password_hash="!",  # Unusable hash until activation
                    is_active=False,
                    is_verified=False,
                    role=emp_role,
                )
                self.session.add(user)
                employee.user_id = new_user_id
                self.session.add(employee)
                await self.session.flush()
                return user

        return None

    async def assign_employees(self, department_uuid: uuid.UUID, employee_uuids: list[uuid.UUID]) -> None:
        await self.session.execute(
            update(Employee)
            .where(Employee.id.in_(employee_uuids))
            .values(department_id=department_uuid)
        )

    async def remove_employee_from_department(self, employee_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(Employee)
            .where(Employee.id == employee_uuid)
            .values(department_id=None)
        )

    async def get_department_employees(self, department_uuid: uuid.UUID) -> list[Employee]:
        result = await self.session.execute(
            select(Employee).where(
                and_(Employee.department_id == department_uuid, Employee.is_deleted == False)  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_sub_departments_count(self, department_uuid: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Department).where(
            and_(Department.parent_department_id == department_uuid, Department.is_deleted == False)  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0
