"""Leave Repository: async database queries for Leave Requests and Policies."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leave import LeaveRequest
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class LeaveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_leave_by_id(self, leave_id: uuid.UUID, for_update: bool = False) -> LeaveRequest | None:
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.id == leave_id)
            .options(
                selectinload(LeaveRequest.employee).selectinload(Employee.department_rel)
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_leaves_for_employee(self, employee_id: uuid.UUID, limit: int = 100) -> list[LeaveRequest]:
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .options(
                selectinload(LeaveRequest.employee).selectinload(Employee.department_rel)
            )
            .order_by(LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pending_leaves(
        self, company_id: uuid.UUID, manager_employee_id: uuid.UUID | None = None, limit: int = 100
    ) -> list[LeaveRequest]:
        conditions = [
            LeaveRequest.status == "PENDING",
            Employee.company_id == company_id,
            Employee.is_deleted == False,
        ]
        if manager_employee_id:
            conditions.append(
                or_(
                    Employee.reporting_manager_id == manager_employee_id,
                    Employee.manager_id == manager_employee_id,
                )
            )

        stmt = (
            select(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .where(and_(*conditions))
            .order_by(LeaveRequest.start_date.asc())
            .options(
                selectinload(LeaveRequest.employee).selectinload(Employee.department_rel)
            )
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def check_leave_overlap(
        self, employee_id: uuid.UUID, start_date: date, end_date: date, exclude_leave_id: uuid.UUID | None = None
    ) -> bool:
        stmt = (
            select(LeaveRequest.id)
            .where(
                and_(
                    LeaveRequest.employee_id == employee_id,
                    LeaveRequest.status.in_(["PENDING", "APPROVED"]),
                    LeaveRequest.start_date <= end_date,
                    LeaveRequest.end_date >= start_date,
                )
            )
        )
        if exclude_leave_id:
            stmt = stmt.where(LeaveRequest.id != exclude_leave_id)
        stmt = stmt.limit(1)
        res = await self.session.execute(stmt)
        return res.first() is not None

    async def get_employee_leave_policies(self, employee_id: uuid.UUID) -> list[EmployeeLeavePolicy]:
        stmt = select(EmployeeLeavePolicy).where(EmployeeLeavePolicy.employee_id == employee_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_employee_leave_policy_by_type(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        target_date: date | None = None,
        for_update: bool = False,
    ) -> EmployeeLeavePolicy | None:
        conditions = [
            EmployeeLeavePolicy.employee_id == employee_id,
            EmployeeLeavePolicy.leave_type == leave_type,
        ]
        if target_date:
            conditions.extend([
                or_(EmployeeLeavePolicy.effective_from == None, EmployeeLeavePolicy.effective_from <= target_date),
                or_(EmployeeLeavePolicy.effective_to == None, EmployeeLeavePolicy.effective_to >= target_date),
            ])

        stmt = select(EmployeeLeavePolicy).where(and_(*conditions))
        if for_update:
            stmt = stmt.with_for_update()
        stmt = stmt.order_by(EmployeeLeavePolicy.created_at.desc()).limit(1)

        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def ensure_employee_leave_policy(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        total_days: Decimal,
        effective_from: date | None = None,
        effective_to: date | None = None,
    ) -> EmployeeLeavePolicy:
        """Insert default policy with ON CONFLICT DO NOTHING, then retrieve it."""
        bind = getattr(self.session, "bind", None)
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "postgresql")

        if dialect_name == "postgresql":
            stmt = (
                pg_insert(EmployeeLeavePolicy)
                .values(
                    id=uuid.uuid4(),
                    employee_id=employee_id,
                    leave_type=leave_type,
                    total_days=total_days,
                    used_days=Decimal("0.0"),
                    carry_forward=False,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
                .on_conflict_do_nothing(index_elements=["employee_id", "leave_type"])
            )
            await self.session.execute(stmt)
            await self.session.flush()
        else:
            # SQLite or mock engine fallback
            existing = await self.get_employee_leave_policy_by_type(employee_id, leave_type)
            if not existing:
                try:
                    stmt = (
                        sqlite_insert(EmployeeLeavePolicy)
                        .values(
                            id=uuid.uuid4(),
                            employee_id=employee_id,
                            leave_type=leave_type,
                            total_days=total_days,
                            used_days=Decimal("0.0"),
                            carry_forward=False,
                            effective_from=effective_from,
                            effective_to=effective_to,
                        )
                        .on_conflict_do_nothing(index_elements=["employee_id", "leave_type"])
                    )
                    await self.session.execute(stmt)
                    await self.session.flush()
                except Exception:
                    policy = EmployeeLeavePolicy(
                        id=uuid.uuid4(),
                        employee_id=employee_id,
                        leave_type=leave_type,
                        total_days=total_days,
                        used_days=Decimal("0.0"),
                        carry_forward=False,
                        effective_from=effective_from,
                        effective_to=effective_to,
                    )
                    self.session.add(policy)
                    try:
                        await self.session.flush()
                    except Exception:
                        pass

        # Select and return the policy row
        policy = await self.get_employee_leave_policy_by_type(employee_id, leave_type, target_date=effective_from)
        if not policy:
            # Fallback query without target_date filter
            policy = await self.get_employee_leave_policy_by_type(employee_id, leave_type)
        return policy

    async def get_pending_leave_days_by_type(
        self, employee_id: uuid.UUID, leave_type: str, exclude_leave_id: uuid.UUID | None = None
    ) -> Decimal:
        """Sum total_days of all PENDING leave requests for this employee and leave type."""
        stmt = select(func.coalesce(func.sum(LeaveRequest.total_days), Decimal("0.0"))).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type == leave_type,
            LeaveRequest.status == "PENDING",
        )
        if exclude_leave_id:
            stmt = stmt.where(LeaveRequest.id != exclude_leave_id)
        res = await self.session.execute(stmt)
        val = res.scalar()
        return Decimal(str(val or 0.0))

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        stmt = (
            select(Employee)
            .where(Employee.user_id == user_id, Employee.is_deleted == False)
            .options(selectinload(Employee.department_rel))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_employee_by_id(self, employee_id: uuid.UUID) -> Employee | None:
        stmt = (
            select(Employee)
            .where(Employee.id == employee_id, Employee.is_deleted == False)
            .options(selectinload(Employee.department_rel))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_company_employees(
        self, company_id: uuid.UUID, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Employee]:
        stmt = (
            select(Employee)
            .options(selectinload(Employee.department_rel))
            .where(Employee.company_id == company_id, Employee.is_deleted == False)
        )
        if search and search.strip():
            pat = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(pat),
                    Employee.last_name.ilike(pat),
                    Employee.employee_id.ilike(pat),
                    Employee.department.ilike(pat),
                    Employee.designation.ilike(pat),
                )
            )
        stmt = stmt.order_by(Employee.first_name.asc(), Employee.last_name.asc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_leave_request(self, **kwargs) -> LeaveRequest:
        leave = LeaveRequest(**kwargs)
        self.session.add(leave)
        return leave
