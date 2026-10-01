"""Leave request business logic layer."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, BadRequestException
from app.models.leave import LeaveRequest
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.repositories.leave_repository import LeaveRepository
from app.schemas.leave import LeaveRequestCreate, LeaveBalanceResponse

logger = logging.getLogger(__name__)

DEFAULT_LEAVE_ALLOCATIONS = [
    {"leave_type": "Sick Leave", "total_days": Decimal("12.0")},
    {"leave_type": "Casual Leave", "total_days": Decimal("10.0")},
    {"leave_type": "Vacation Leave", "total_days": Decimal("15.0")},
]


class LeaveService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LeaveRepository(session)

    async def get_leave_balances(self, employee_id: uuid.UUID) -> list[LeaveBalanceResponse]:
        policies = await self.repo.get_employee_leave_policies(employee_id)
        
        if not policies:
            return []
            
        balances = []
        for p in policies:
            total = float(p.total_days)
            used = float(p.used_days)
            balances.append(
                LeaveBalanceResponse(
                    leave_type=p.leave_type,
                    total_days=total,
                    used_days=used,
                    remaining_days=max(0.0, total - used)
                )
            )
        return balances

    async def apply_leave(self, employee_id: uuid.UUID, data: LeaveRequestCreate) -> LeaveRequest:
        if data.start_date > data.end_date:
            raise BadRequestException(message="Start date must be before or equal to End date.")

        # Check for overlaps
        has_overlap = await self.repo.check_leave_overlap(employee_id, data.start_date, data.end_date)
        if has_overlap:
            raise BadRequestException(message="You have an overlapping leave request that is active or pending.")

        # Check balance
        policy = await self.repo.get_employee_leave_policy_by_type(employee_id, data.leave_type)
        if not policy:
            # If policy doesn't exist, we resolve default allocations dynamically
            default_alloc = next((x for x in DEFAULT_LEAVE_ALLOCATIONS if x["leave_type"] == data.leave_type), None)
            if not default_alloc:
                raise BadRequestException(message=f"Leave type {data.leave_type} is not supported.")
            
            policy = EmployeeLeavePolicy(
                employee_id=employee_id,
                leave_type=data.leave_type,
                total_days=default_alloc["total_days"],
                used_days=Decimal("0.0"),
                carry_forward=False,
                effective_from=date(date.today().year, 1, 1),
                effective_to=date(date.today().year, 12, 31)
            )
            self.session.add(policy)
            await self.session.flush()

        remaining = float(policy.total_days - policy.used_days)
        if remaining < float(data.total_days):
            raise BadRequestException(message=f"Insufficient leave balance. Remaining: {remaining} days.")

        # Create leave request
        new_leave = await self.repo.create_leave_request(
            employee_id=employee_id,
            leave_type=data.leave_type,
            start_date=data.start_date,
            end_date=data.end_date,
            total_days=data.total_days,
            reason=data.reason,
            status="PENDING"
        )

        # Notify approving manager
        from app.models.employee import Employee
        from app.models.user import User
        from sqlalchemy import select
        from app.services import notification_service

        emp = await self.session.get(Employee, employee_id)
        if emp and emp.company_id:
            manager_user_id = None
            mgr_id = emp.reporting_manager_id or emp.manager_id
            if mgr_id:
                mgr = await self.session.get(Employee, mgr_id)
                if mgr and mgr.user_id:
                    manager_user_id = mgr.user_id

            recipient_ids = [manager_user_id] if manager_user_id else []
            if not recipient_ids:
                admin_res = await self.session.execute(
                    select(User.id).where(
                        User.company_id == emp.company_id,
                        User.role.in_(["hr_admin", "manager", "super_admin", "admin"])
                    ).limit(5)
                )
                recipient_ids = list(admin_res.scalars().all())

            if recipient_ids:
                await notification_service.notify(
                    self.session,
                    company_id=emp.company_id,
                    recipient_ids=recipient_ids,
                    type="leave.requested",
                    category="leave",
                    module="leave",
                    title=f"Leave Request: {emp.first_name} {emp.last_name}",
                    body=f"{emp.first_name} {emp.last_name} requested {data.total_days} day(s) of {data.leave_type}.",
                    link="/dashboard/leaves",
                    priority="normal",
                    entity={"type": "leave_request", "id": str(new_leave.id)},
                    actor_id=emp.user_id,
                    dedupe_key=f"leave:{new_leave.id}:requested",
                )

        await self.session.commit()
        await self.session.refresh(new_leave)
        return new_leave

    async def get_employee_leaves(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        return await self.repo.get_leaves_for_employee(employee_id)

    async def get_pending_leaves(self, company_id: uuid.UUID) -> list[LeaveRequest]:
        return await self.repo.get_pending_leaves(company_id)

    async def review_leave(
        self, leave_id: uuid.UUID, status: str, approved_by_id: uuid.UUID, rejection_reason: str | None = None
    ) -> LeaveRequest:
        leave = await self.repo.get_leave_by_id(leave_id)
        if not leave:
            raise NotFoundException(message="Leave request not found.")

        if leave.status != "PENDING":
            raise BadRequestException(message="Leave request is not in PENDING state.")

        leave.status = status
        if status == "APPROVED":
            leave.approved_by_id = approved_by_id
            leave.rejection_reason = None

            # Deduct balance
            policy = await self.repo.get_employee_leave_policy_by_type(leave.employee_id, leave.leave_type)
            if policy:
                policy.used_days += leave.total_days
        elif status == "REJECTED":
            if not rejection_reason:
                raise BadRequestException(message="Rejection reason is required.")
            leave.rejection_reason = rejection_reason
            leave.approved_by_id = None

        # Notify requester
        from app.models.employee import Employee
        from app.services import notification_service

        emp = await self.session.get(Employee, leave.employee_id)
        if emp and emp.user_id and emp.company_id:
            is_approved = status == "APPROVED"
            title = f"Leave Request {'Approved' if is_approved else 'Rejected'}: {leave.leave_type}"
            body = (
                f"Your {leave.leave_type} leave request for {leave.total_days} day(s) has been approved."
                if is_approved
                else f"Your {leave.leave_type} leave request was rejected: {rejection_reason or 'No reason provided'}."
            )
            dedupe_action = "approved" if is_approved else "rejected"
            await notification_service.notify(
                self.session,
                company_id=emp.company_id,
                recipient_ids=[emp.user_id],
                type=f"leave.{dedupe_action}",
                category="leave",
                module="leave",
                title=title,
                body=body,
                link="/dashboard/leaves",
                priority="high" if is_approved else "normal",
                entity={"type": "leave_request", "id": str(leave.id)},
                actor_id=approved_by_id,
                dedupe_key=f"leave:{leave.id}:{dedupe_action}",
            )

        await self.session.commit()
        await self.session.refresh(leave)
        return leave
