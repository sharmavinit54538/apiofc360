"""Leave Repository: async database queries for Leave Requests and Policies."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leave import LeaveRequest
from app.models.employee_leave_policy import EmployeeLeavePolicy

from app.models.employee import Employee

logger = logging.getLogger(__name__)


class LeaveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_leave_by_id(self, leave_id: uuid.UUID) -> LeaveRequest | None:
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.id == leave_id)
            .options(selectinload(LeaveRequest.employee))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_leaves_for_employee(self, employee_id: uuid.UUID, limit: int = 100) -> list[LeaveRequest]:
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .order_by(LeaveRequest.start_date.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pending_leaves(self, company_id: uuid.UUID, limit: int = 100) -> list[LeaveRequest]:
        stmt = (
            select(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .where(
                and_(
                    LeaveRequest.status == "PENDING",
                    Employee.company_id == company_id,
                    Employee.is_deleted == False
                )
            )
            .order_by(LeaveRequest.start_date.asc())
            .options(selectinload(LeaveRequest.employee))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def check_leave_overlap(self, employee_id: uuid.UUID, start_date: date, end_date: date) -> bool:
        stmt = (
            select(LeaveRequest)
            .where(
                and_(
                    LeaveRequest.employee_id == employee_id,
                    LeaveRequest.status.in_(["PENDING", "APPROVED"]),
                    or_(
                        and_(LeaveRequest.start_date <= start_date, LeaveRequest.end_date >= start_date),
                        and_(LeaveRequest.start_date <= end_date, LeaveRequest.end_date >= end_date),
                        and_(LeaveRequest.start_date >= start_date, LeaveRequest.end_date <= end_date)
                    )
                )
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none() is not None

    async def get_employee_leave_policies(self, employee_id: uuid.UUID) -> list[EmployeeLeavePolicy]:
        stmt = select(EmployeeLeavePolicy).where(EmployeeLeavePolicy.employee_id == employee_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_employee_leave_policy_by_type(
        self, employee_id: uuid.UUID, leave_type: str
    ) -> EmployeeLeavePolicy | None:
        stmt = select(EmployeeLeavePolicy).where(
            and_(
                EmployeeLeavePolicy.employee_id == employee_id,
                EmployeeLeavePolicy.leave_type == leave_type
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_leave_request(self, **kwargs) -> LeaveRequest:
        leave = LeaveRequest(**kwargs)
        self.session.add(leave)
        return leave
