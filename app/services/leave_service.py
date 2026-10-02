"""Leave request business logic layer."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.leave import LeaveRequest
from app.models.user import User
from app.repositories.leave_repository import LeaveRepository
from app.schemas.leave import (
    LeaveBalanceResponse,
    LeaveEmployeeItem,
    LeaveRequestCreate,
)

logger = logging.getLogger(__name__)

DEFAULT_LEAVE_ALLOCATIONS = [
    {"leave_type": "Sick Leave", "total_days": Decimal("12.0")},
    {"leave_type": "Casual Leave", "total_days": Decimal("10.0")},
    {"leave_type": "Vacation Leave", "total_days": Decimal("15.0")},
]


def calculate_leave_days(start_date: date, end_date: date) -> Decimal:
    """Calculate inclusive calendar days between start_date and end_date."""
    if start_date > end_date:
        return Decimal("0.0")
    days = (end_date - start_date).days + 1
    return Decimal(str(days))


class LeaveService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LeaveRepository(session)

    async def get_leave_balances(self, employee_id: uuid.UUID) -> list[LeaveBalanceResponse]:
        """Ensure all 3 leave types exist and return balances in fixed order: Sick, Casual, Vacation."""
        current_year = date.today().year
        effective_from = date(current_year, 1, 1)
        effective_to = date(current_year, 12, 31)

        for alloc in DEFAULT_LEAVE_ALLOCATIONS:
            await self.repo.ensure_employee_leave_policy(
                employee_id=employee_id,
                leave_type=alloc["leave_type"],
                total_days=alloc["total_days"],
                effective_from=effective_from,
                effective_to=effective_to,
            )
        await self.session.commit()

        policies = await self.repo.get_employee_leave_policies(employee_id)
        policy_map = {p.leave_type: p for p in policies}

        order = ["Sick Leave", "Casual Leave", "Vacation Leave"]
        balances: list[LeaveBalanceResponse] = []
        for ltype in order:
            p = policy_map.get(ltype)
            if p:
                total = float(p.total_days)
                used = float(p.used_days)
                balances.append(
                    LeaveBalanceResponse(
                        leave_type=p.leave_type,
                        total_days=total,
                        used_days=used,
                        remaining_days=max(0.0, total - used),
                    )
                )
            else:
                default_alloc = next((x for x in DEFAULT_LEAVE_ALLOCATIONS if x["leave_type"] == ltype), None)
                tot = float(default_alloc["total_days"]) if default_alloc else 0.0
                balances.append(
                    LeaveBalanceResponse(
                        leave_type=ltype,
                        total_days=tot,
                        used_days=0.0,
                        remaining_days=tot,
                    )
                )
        return balances

    async def apply_leave(
        self,
        employee_id: uuid.UUID,
        data: LeaveRequestCreate,
        role: str = "employee",
        backdate_grace_days: int = 0,
    ) -> LeaveRequest:
        """Apply for leave with server-side day calculation, backdating check, and pending reservation."""
        if data.start_date > data.end_date:
            raise BadRequestException(message="Start date must be before or equal to End date.")

        # Compute total days server-side, ignoring any client-provided total_days
        calculated_days = calculate_leave_days(data.start_date, data.end_date)
        if calculated_days <= Decimal("0.0"):
            raise BadRequestException(message="Invalid leave date range.")

        # Reject start_date in the past beyond configurable grace (default 0 days), except for HR/Super admins
        if role.lower() not in ("hr_admin", "super_admin"):
            today = date.today()
            from datetime import timedelta
            allowed_past_date = today - timedelta(days=backdate_grace_days)
            if data.start_date < allowed_past_date:
                raise BadRequestException(message="Leave cannot be applied for past dates.")

        # Check for active or pending overlapping leaves
        has_overlap = await self.repo.check_leave_overlap(employee_id, data.start_date, data.end_date)
        if has_overlap:
            raise BadRequestException(message="You have an overlapping leave request that is active or pending.")

        # Check policy coverage for the start_date
        policy = await self.repo.get_employee_leave_policy_by_type(
            employee_id, data.leave_type, target_date=data.start_date
        )
        if not policy:
            default_alloc = next((x for x in DEFAULT_LEAVE_ALLOCATIONS if x["leave_type"] == data.leave_type), None)
            if not default_alloc:
                raise BadRequestException(message=f"Leave type {data.leave_type} is not supported.")

            policy = await self.repo.ensure_employee_leave_policy(
                employee_id=employee_id,
                leave_type=data.leave_type,
                total_days=default_alloc["total_days"],
                effective_from=date(data.start_date.year, 1, 1),
                effective_to=date(data.start_date.year, 12, 31),
            )

        # Count PENDING requests of the same type as reserved: remaining = total - used - sum(pending)
        pending_days = await self.repo.get_pending_leave_days_by_type(employee_id, data.leave_type)
        available_days = policy.total_days - policy.used_days - pending_days
        if available_days < calculated_days:
            raise BadRequestException(
                message=f"Insufficient leave balance. Available (after reserving pending requests): {float(available_days)} days, requested: {float(calculated_days)} days."
            )

        # Create leave request
        new_leave = await self.repo.create_leave_request(
            employee_id=employee_id,
            leave_type=data.leave_type,
            start_date=data.start_date,
            end_date=data.end_date,
            total_days=calculated_days,
            reason=data.reason,
            status="PENDING",
        )

        # Notify approving manager
        emp = await self.session.get(Employee, employee_id)
        if emp and emp.company_id:
            from app.services import notification_service

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
                        User.role.in_(["hr_admin", "manager", "super_admin", "admin"]),
                    ).limit(5)
                )
                recipient_ids = list(admin_res.scalars().all())

            if recipient_ids:
                try:
                    await notification_service.notify(
                        self.session,
                        company_id=emp.company_id,
                        recipient_ids=recipient_ids,
                        type="leave.requested",
                        category="leave",
                        module="leave",
                        title=f"Leave Request: {emp.first_name} {emp.last_name}",
                        body=f"{emp.first_name} {emp.last_name} requested {calculated_days} day(s) of {data.leave_type}.",
                        link="/dashboard/leaves",
                        priority="normal",
                        entity={"type": "leave_request", "id": str(new_leave.id)},
                        actor_id=emp.user_id,
                        dedupe_key=f"leave:{new_leave.id}:requested",
                    )
                except Exception as notif_err:
                    logger.warning("Failed to dispatch leave requested notification: %s", notif_err)

        await self.session.commit()
        await self.session.refresh(new_leave)
        return new_leave

    async def get_employee_leaves(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        return await self.repo.get_leaves_for_employee(employee_id)

    async def get_pending_leaves(
        self,
        company_id: uuid.UUID,
        caller_user_id: uuid.UUID | None = None,
        caller_role: str = "hr_admin",
    ) -> list[LeaveRequest]:
        """Fetch pending leaves. Managers only see their direct reports; HR Admin sees entire company."""
        manager_employee_id = None
        if caller_role.lower() == "manager" and caller_user_id:
            mgr_emp = await self.repo.get_employee_by_user_id(caller_user_id)
            manager_employee_id = mgr_emp.id if mgr_emp else uuid.uuid4()

        return await self.repo.get_pending_leaves(company_id, manager_employee_id=manager_employee_id)

    async def review_leave(
        self,
        leave_id: uuid.UUID,
        status: str,
        reviewer_user_id: uuid.UUID,
        reviewer_role: str,
        reviewer_company_id: uuid.UUID,
        rejection_reason: str | None = None,
    ) -> LeaveRequest:
        """Review leave with FOR UPDATE locking, tenant check, self-review guard, and manager hierarchy check."""
        leave = await self.repo.get_leave_by_id(leave_id, for_update=True)
        if not leave:
            raise NotFoundException(message="Leave request not found.")

        # Tenant isolation (IDOR Prevention)
        emp = leave.employee
        if not emp or emp.company_id != reviewer_company_id:
            raise NotFoundException(message="Leave request not found.")

        # Self-approval guard
        if emp.user_id == reviewer_user_id:
            raise AppException(
                message="You cannot approve or reject your own leave request.",
                status_code=403,
            )

        # Manager scope enforcement: can only review their direct reports
        if reviewer_role.lower() == "manager":
            mgr_emp = await self.repo.get_employee_by_user_id(reviewer_user_id)
            if not mgr_emp or (emp.reporting_manager_id != mgr_emp.id and emp.manager_id != mgr_emp.id):
                raise AppException(
                    message="You can only review leave requests for your direct reports.",
                    status_code=403,
                )

        if leave.status != "PENDING":
            raise BadRequestException(message="Leave request is not in PENDING state.")

        if status == "APPROVED":
            leave.approved_by_id = reviewer_user_id
            leave.rejection_reason = None

            # Concurrency & Balance Integrity: lock policy row and re-verify remaining balance
            policy = await self.repo.get_employee_leave_policy_by_type(
                leave.employee_id, leave.leave_type, target_date=leave.start_date, for_update=True
            )
            if not policy:
                raise BadRequestException(message=f"No active leave policy found for {leave.leave_type}.")

            remaining = policy.total_days - policy.used_days
            if remaining < leave.total_days:
                raise BadRequestException(
                    message=f"Insufficient leave balance to approve this request. Remaining: {float(remaining)} days, required: {float(leave.total_days)} days."
                )

            # Deduct balance
            policy.used_days += leave.total_days
            leave.status = "APPROVED"

        elif status == "REJECTED":
            if not rejection_reason or not rejection_reason.strip():
                raise BadRequestException(message="Rejection reason is required.")
            leave.rejection_reason = rejection_reason.strip()
            leave.approved_by_id = None
            leave.status = "REJECTED"
        else:
            raise BadRequestException(message=f"Invalid review status: {status}")

        # Notify requester
        if emp and emp.user_id and emp.company_id:
            from app.services import notification_service

            is_approved = status == "APPROVED"
            title = f"Leave Request {'Approved' if is_approved else 'Rejected'}: {leave.leave_type}"
            body = (
                f"Your {leave.leave_type} leave request for {leave.total_days} day(s) has been approved."
                if is_approved
                else f"Your {leave.leave_type} leave request was rejected: {rejection_reason or 'No reason provided'}."
            )
            dedupe_action = "approved" if is_approved else "rejected"
            try:
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
                    actor_id=reviewer_user_id,
                    dedupe_key=f"leave:{leave.id}:{dedupe_action}",
                )
            except Exception as notif_err:
                logger.warning("Failed to dispatch leave reviewed notification: %s", notif_err)

        await self.session.commit()
        await self.session.refresh(leave)
        return leave

    async def cancel_leave(
        self,
        leave_id: uuid.UUID,
        caller_user_id: uuid.UUID,
        caller_role: str,
        caller_company_id: uuid.UUID,
    ) -> LeaveRequest:
        """Cancel a leave request. PENDING -> CANCELLED (no balance change); APPROVED & future start_date -> CANCELLED + refund."""
        leave = await self.repo.get_leave_by_id(leave_id, for_update=True)
        if not leave:
            raise NotFoundException(message="Leave request not found.")

        # Tenant isolation
        emp = leave.employee
        if not emp or emp.company_id != caller_company_id:
            raise NotFoundException(message="Leave request not found.")

        # Ownership / Role check: only owner or hr_admin/super_admin can cancel
        is_owner = emp.user_id == caller_user_id
        is_admin = caller_role.lower() in ("hr_admin", "super_admin")
        if not (is_owner or is_admin):
            raise AppException(message="You can only cancel your own leave requests.", status_code=403)

        if leave.status == "PENDING":
            leave.status = "CANCELLED"
            # No balance change needed for pending leaves
        elif leave.status == "APPROVED":
            today = date.today()
            if leave.start_date <= today:
                raise BadRequestException(message="Cannot cancel an approved leave that has already started or passed.")

            leave.status = "CANCELLED"
            # Refund used_days
            policy = await self.repo.get_employee_leave_policy_by_type(
                leave.employee_id, leave.leave_type, target_date=leave.start_date, for_update=True
            )
            if policy:
                policy.used_days = max(Decimal("0.0"), policy.used_days - leave.total_days)
        elif leave.status in ("CANCELLED", "REJECTED"):
            raise BadRequestException(message=f"Leave request is already {leave.status.lower()}.")
        else:
            raise BadRequestException(message=f"Cannot cancel leave request in status {leave.status}.")

        await self.session.commit()
        await self.session.refresh(leave)
        return leave

    async def get_company_employees(
        self,
        company_id: uuid.UUID,
        search: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[LeaveEmployeeItem]:
        """List employees in the caller's company for HR Admin dropdown/management."""
        offset = (page - 1) * limit
        employees = await self.repo.get_company_employees(
            company_id=company_id, search=search, limit=limit, offset=offset
        )
        items: list[LeaveEmployeeItem] = []
        for emp in employees:
            first = emp.first_name or ""
            last = emp.last_name or ""
            full_name = f"{first} {last}".strip() or "Employee"

            dept_name = None
            if getattr(emp, "department_rel", None) and emp.department_rel:
                dept_name = getattr(emp.department_rel, "department_name", None) or getattr(emp.department_rel, "name", None)
            if not dept_name:
                dept_name = emp.department or ""

            items.append(
                LeaveEmployeeItem(
                    id=emp.id,
                    employee_code=emp.employee_id,
                    full_name=full_name,
                    department=dept_name,
                    designation=emp.designation or "",
                )
            )
        return items
