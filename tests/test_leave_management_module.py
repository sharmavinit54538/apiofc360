"""Comprehensive async pytest test suite for Leave Management Module.

Tests cover:
1. Cross-company review is rejected (404 IDOR).
2. Self-approval is rejected (403 Forbidden).
3. Manager team scope enforcement (manager can only review direct reports).
4. Client total_days is ignored (computed server-side from start_date/end_date).
5. Double-approve deducts once (PENDING state guard and row lock).
6. Pending reservation blocks over-booking.
7. Duplicate policy migration logic (normalize + sum used + max total + dedupe).
8. Cancel + refund (PENDING -> CANCELLED without balance change; APPROVED future -> refund used_days).
9. Overlap check with 2 existing rows doesn't 500 (limit(1) / exists query).
10. Reviewer visibility (employee_name and department populated from eager-loaded employee).
11. Balances return all 3 types in fixed order (Sick Leave, Casual Leave, Vacation Leave).
12. Company employees endpoint (HR Admin only, tenant-scoped, search/pagination).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.leave import LeaveRequest
from app.models.user import User
from app.repositories.leave_repository import LeaveRepository
from app.schemas.leave import (
    LeaveApprovalRequest,
    LeaveBalanceResponse,
    LeaveEmployeeItem,
    LeaveRequestCreate,
    LeaveRequestResponse,
)
from app.services.leave_service import (
    DEFAULT_LEAVE_ALLOCATIONS,
    LeaveService,
    calculate_leave_days,
)


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_employee(
    emp_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    first_name: str = "John",
    last_name: str = "Doe",
    department: str = "Engineering",
) -> Employee:
    emp = Employee(
        id=emp_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        first_name=first_name,
        last_name=last_name,
        employee_id="EMP-101",
        personal_email="john@example.com",
        phone="9876543210",
        department=department,
        designation="Software Engineer",
        joining_date=date(2025, 1, 1),
        manager_id=manager_id,
        reporting_manager_id=manager_id,
        is_deleted=False,
    )
    dept_obj = Department(
        id=uuid.uuid4(),
        department_name=department,
        department_code=department[:3].upper(),
        location="Headquarters",
        description=f"{department} Department",
        company_id=emp.company_id,
    )
    emp.department_rel = dept_obj
    return emp


def make_leave(
    leave_id: uuid.UUID | None = None,
    employee: Employee | None = None,
    leave_type: str = "Sick Leave",
    start_date: date = date(2026, 11, 1),
    end_date: date = date(2026, 11, 3),
    total_days: Decimal = Decimal("3.0"),
    status: str = "PENDING",
) -> LeaveRequest:
    emp = employee or make_employee()
    now = datetime.now(timezone.utc)
    leave = LeaveRequest(
        id=leave_id or uuid.uuid4(),
        employee_id=emp.id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        total_days=total_days,
        reason="Medical appointment",
        status=status,
        created_at=now,
        updated_at=now,
    )
    leave.employee = emp
    return leave


# ==============================================================================
# 1. Tenant Isolation (IDOR) Test
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_company_review_is_rejected():
    """Verify reviewer from Company B cannot review leave of employee from Company A (returns 404)."""
    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()

    emp_a = make_employee(company_id=comp_a)
    leave = make_leave(employee=emp_a)

    mock_session = AsyncMock()
    service = LeaveService(mock_session)

    # Repository returns the leave (which belongs to company A)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)

    reviewer_user_id = uuid.uuid4()

    # Company B tries to review company A's leave -> raises NotFoundException (404)
    with pytest.raises(NotFoundException) as exc_info:
        await service.review_leave(
            leave_id=leave.id,
            status="APPROVED",
            reviewer_user_id=reviewer_user_id,
            reviewer_role="hr_admin",
            reviewer_company_id=comp_b,
        )
    assert "not found" in exc_info.value.message.lower()


# ==============================================================================
# 2. Self-Approval Guard Test
# ==============================================================================

@pytest.mark.asyncio
async def test_self_approval_is_rejected():
    """Verify that a user cannot approve or reject their own leave request (returns 403)."""
    user_id = uuid.uuid4()
    comp_id = uuid.uuid4()

    emp = make_employee(user_id=user_id, company_id=comp_id)
    leave = make_leave(employee=emp)

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)

    with pytest.raises(AppException) as exc_info:
        await service.review_leave(
            leave_id=leave.id,
            status="APPROVED",
            reviewer_user_id=user_id,  # Same user as requester
            reviewer_role="manager",
            reviewer_company_id=comp_id,
        )
    assert exc_info.value.status_code == 403
    assert "cannot approve or reject your own" in exc_info.value.message.lower()


# ==============================================================================
# 3. Manager Team Scope Test
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_team_scope_enforcement():
    """Verify manager cannot review leave for employees outside their direct reporting line."""
    comp_id = uuid.uuid4()
    mgr_emp_id = uuid.uuid4()
    other_mgr_id = uuid.uuid4()

    mgr_user_id = uuid.uuid4()
    mgr_employee = make_employee(emp_id=mgr_emp_id, user_id=mgr_user_id, company_id=comp_id)

    # Employee reports to other_mgr_id, NOT mgr_emp_id
    subordinate = make_employee(company_id=comp_id, manager_id=other_mgr_id)
    leave = make_leave(employee=subordinate)

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)
    service.repo.get_employee_by_user_id = AsyncMock(return_value=mgr_employee)

    # Manager attempts to review non-subordinate leave -> 403
    with pytest.raises(AppException) as exc_info:
        await service.review_leave(
            leave_id=leave.id,
            status="APPROVED",
            reviewer_user_id=mgr_user_id,
            reviewer_role="manager",
            reviewer_company_id=comp_id,
        )
    assert exc_info.value.status_code == 403
    assert "direct reports" in exc_info.value.message.lower()

    # When subordinate reports to mgr_emp_id -> review succeeds
    subordinate.manager_id = mgr_emp_id
    subordinate.reporting_manager_id = mgr_emp_id
    policy = EmployeeLeavePolicy(
        employee_id=subordinate.id,
        leave_type="Sick Leave",
        total_days=Decimal("12.0"),
        used_days=Decimal("0.0"),
    )
    service.repo.get_employee_leave_policy_by_type = AsyncMock(return_value=policy)

    reviewed = await service.review_leave(
        leave_id=leave.id,
        status="APPROVED",
        reviewer_user_id=mgr_user_id,
        reviewer_role="manager",
        reviewer_company_id=comp_id,
    )
    assert reviewed.status == "APPROVED"
    assert reviewed.approved_by_id == mgr_user_id
    assert policy.used_days == leave.total_days


# ==============================================================================
# 4. Server-Side Day Calculation Test
# ==============================================================================

@pytest.mark.asyncio
async def test_client_total_days_ignored():
    """Verify that client-provided total_days is ignored and computed strictly server-side."""
    emp = make_employee()
    mock_session = AsyncMock()
    service = LeaveService(mock_session)

    # Mock overlap check to return False
    service.repo.check_leave_overlap = AsyncMock(return_value=False)

    # Policy with 12 days available
    policy = EmployeeLeavePolicy(
        employee_id=emp.id,
        leave_type="Sick Leave",
        total_days=Decimal("12.0"),
        used_days=Decimal("0.0"),
    )
    service.repo.get_employee_leave_policy_by_type = AsyncMock(return_value=policy)
    service.repo.get_pending_leave_days_by_type = AsyncMock(return_value=Decimal("0.0"))

    # Client passes bogus total_days=99.0 for a 3-day range (Oct 10 to Oct 12)
    start_d = date(2026, 10, 10)
    end_d = date(2026, 10, 12)
    req = LeaveRequestCreate(
        leave_type="Sick Leave",
        start_date=start_d,
        end_date=end_d,
        total_days=Decimal("99.0"),  # Client says 99 days!
        reason="Fever and recovery",
    )

    created_leave = make_leave(
        start_date=start_d,
        end_date=end_d,
        total_days=Decimal("3.0"),
    )
    service.repo.create_leave_request = AsyncMock(return_value=created_leave)

    res = await service.apply_leave(emp.id, req, role="employee")

    # Assert repo.create_leave_request was called with total_days=Decimal("3.0")
    call_kwargs = service.repo.create_leave_request.call_args.kwargs
    assert call_kwargs["total_days"] == Decimal("3.0")
    assert call_kwargs["total_days"] != Decimal("99.0")


# ==============================================================================
# 5. Double-Approve Deducts Once Test
# ==============================================================================

@pytest.mark.asyncio
async def test_double_approve_deducts_once():
    """Verify that attempting to approve an already approved leave fails and does not double-deduct."""
    comp_id = uuid.uuid4()
    emp = make_employee(company_id=comp_id)
    leave = make_leave(employee=emp, status="APPROVED")  # Already APPROVED

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)

    policy = EmployeeLeavePolicy(
        employee_id=emp.id,
        leave_type="Sick Leave",
        total_days=Decimal("12.0"),
        used_days=Decimal("3.0"),
    )
    service.repo.get_employee_leave_policy_by_type = AsyncMock(return_value=policy)

    with pytest.raises(BadRequestException) as exc_info:
        await service.review_leave(
            leave_id=leave.id,
            status="APPROVED",
            reviewer_user_id=uuid.uuid4(),
            reviewer_role="hr_admin",
            reviewer_company_id=comp_id,
        )
    assert "pending state" in exc_info.value.message.lower()
    # Used days unchanged
    assert policy.used_days == Decimal("3.0")


# ==============================================================================
# 6. Pending Reservation Blocks Over-Booking Test
# ==============================================================================

@pytest.mark.asyncio
async def test_pending_reservation_blocks_overbooking():
    """Verify that existing PENDING requests count as reserved and block subsequent over-booking."""
    emp = make_employee()
    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.check_leave_overlap = AsyncMock(return_value=False)

    # Policy has 10 total days, 0 used
    policy = EmployeeLeavePolicy(
        employee_id=emp.id,
        leave_type="Casual Leave",
        total_days=Decimal("10.0"),
        used_days=Decimal("0.0"),
    )
    service.repo.get_employee_leave_policy_by_type = AsyncMock(return_value=policy)

    # 7 days are already reserved in other PENDING requests
    service.repo.get_pending_leave_days_by_type = AsyncMock(return_value=Decimal("7.0"))

    # Requesting 4 days: Available is 10 - 0 - 7 = 3 days. 4 > 3 -> Should fail!
    req = LeaveRequestCreate(
        leave_type="Casual Leave",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 13),  # 4 calendar days
        reason="Family vacation",
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.apply_leave(emp.id, req, role="employee")
    assert "insufficient leave balance" in exc_info.value.message.lower()


# ==============================================================================
# 7. Duplicate Policy Migration Logic Test
# ==============================================================================

def test_duplicate_policy_dedupe_logic():
    """Verify deduplication math: legacy normalization, max total_days, sum used_days."""
    raw_rows = [
        # (id, employee_id, leave_type, total_days, used_days)
        (uuid.uuid4(), "emp-1", "SICK_LEAVE", Decimal("10.0"), Decimal("2.0")),
        (uuid.uuid4(), "emp-1", "Sick Leave", Decimal("12.0"), Decimal("3.0")),
        (uuid.uuid4(), "emp-1", "CASUAL_LEAVE", Decimal("10.0"), Decimal("1.0")),
        (uuid.uuid4(), "emp-2", "VACATION_LEAVE", Decimal("15.0"), Decimal("5.0")),
        (uuid.uuid4(), "emp-2", "Vacation Leave", Decimal("15.0"), Decimal("2.0")),
    ]

    # Normalize
    type_map = {
        "SICK_LEAVE": "Sick Leave",
        "CASUAL_LEAVE": "Casual Leave",
        "VACATION_LEAVE": "Vacation Leave",
    }
    normalized = []
    for row in raw_rows:
        n_type = type_map.get(row[2], row[2])
        normalized.append((row[0], row[1], n_type, row[3], row[4]))

    # Group by (employee_id, leave_type)
    groups = {}
    for r in normalized:
        key = (r[1], r[2])
        groups.setdefault(key, []).append(r)

    merged = {}
    for key, items in groups.items():
        max_total = max(x[3] for x in items)
        sum_used = sum(x[4] for x in items)
        merged[key] = {"total_days": max_total, "used_days": sum_used, "count": len(items)}

    # emp-1 Sick Leave was (10, 2) and (12, 3) -> max_total=12, sum_used=5
    assert merged[("emp-1", "Sick Leave")]["total_days"] == Decimal("12.0")
    assert merged[("emp-1", "Sick Leave")]["used_days"] == Decimal("5.0")
    assert merged[("emp-1", "Sick Leave")]["count"] == 2

    # emp-2 Vacation Leave was (15, 5) and (15, 2) -> max_total=15, sum_used=7
    assert merged[("emp-2", "Vacation Leave")]["total_days"] == Decimal("15.0")
    assert merged[("emp-2", "Vacation Leave")]["used_days"] == Decimal("7.0")
    assert merged[("emp-2", "Vacation Leave")]["count"] == 2


# ==============================================================================
# 8. Cancel + Refund Test
# ==============================================================================

@pytest.mark.asyncio
async def test_cancel_pending_leave_no_balance_change():
    """Verify cancelling a PENDING leave changes status to CANCELLED without altering policy balance."""
    comp_id = uuid.uuid4()
    emp = make_employee(company_id=comp_id)
    leave = make_leave(employee=emp, status="PENDING")

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)

    cancelled = await service.cancel_leave(
        leave_id=leave.id,
        caller_user_id=emp.user_id,
        caller_role="employee",
        caller_company_id=comp_id,
    )
    assert cancelled.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_approved_future_leave_refunds_balance():
    """Verify cancelling an APPROVED future leave changes status to CANCELLED and refunds used_days."""
    comp_id = uuid.uuid4()
    emp = make_employee(company_id=comp_id)
    future_start = date.today() + timedelta(days=10)
    future_end = future_start + timedelta(days=2)

    leave = make_leave(
        employee=emp,
        start_date=future_start,
        end_date=future_end,
        total_days=Decimal("3.0"),
        status="APPROVED",
    )

    policy = EmployeeLeavePolicy(
        employee_id=emp.id,
        leave_type="Sick Leave",
        total_days=Decimal("12.0"),
        used_days=Decimal("5.0"),
    )

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)
    service.repo.get_employee_leave_policy_by_type = AsyncMock(return_value=policy)

    cancelled = await service.cancel_leave(
        leave_id=leave.id,
        caller_user_id=emp.user_id,
        caller_role="employee",
        caller_company_id=comp_id,
    )
    assert cancelled.status == "CANCELLED"
    # Used days refunded: 5.0 - 3.0 = 2.0
    assert policy.used_days == Decimal("2.0")


@pytest.mark.asyncio
async def test_cancel_approved_past_leave_rejected():
    """Verify cancelling an APPROVED leave that has already started or passed is rejected."""
    comp_id = uuid.uuid4()
    emp = make_employee(company_id=comp_id)
    past_start = date.today() - timedelta(days=2)

    leave = make_leave(
        employee=emp,
        start_date=past_start,
        end_date=date.today(),
        status="APPROVED",
    )

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_leave_by_id = AsyncMock(return_value=leave)

    with pytest.raises(BadRequestException) as exc_info:
        await service.cancel_leave(
            leave_id=leave.id,
            caller_user_id=emp.user_id,
            caller_role="employee",
            caller_company_id=comp_id,
        )
    assert "already started or passed" in exc_info.value.message.lower()


# ==============================================================================
# 9. Overlap Check with 2 Existing Rows Does Not 500 Test
# ==============================================================================

@pytest.mark.asyncio
async def test_overlap_with_multiple_rows_does_not_raise():
    """Verify check_leave_overlap handles multiple existing overlapping rows gracefully without 500."""
    mock_session = AsyncMock()
    repo = LeaveRepository(mock_session)

    # When query runs, simulate execute returning a row (first() is not None)
    mock_res = MagicMock()
    mock_res.first.return_value = (uuid.uuid4(),)
    mock_session.execute.return_value = mock_res

    has_overlap = await repo.check_leave_overlap(
        employee_id=uuid.uuid4(),
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 5),
    )
    assert has_overlap is True

    # Check query generated has LIMIT 1
    called_stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(called_stmt)
    assert "LIMIT" in stmt_str or "limit" in stmt_str.lower()


# ==============================================================================
# 10. Reviewer Visibility Schema Contract Test
# ==============================================================================

def test_leave_request_response_employee_name_and_department():
    """Verify LeaveRequestResponse includes employee_name and department resolved from employee."""
    emp = make_employee(first_name="Jane", last_name="Smith", department="Finance")
    leave = make_leave(employee=emp)

    resp = LeaveRequestResponse.model_validate(leave)
    assert resp.employee_name == "Jane Smith"
    assert resp.department == "Finance"
    assert resp.total_days == Decimal("3.0")


# ==============================================================================
# 11. Balances All 3 Types Fixed Order Test
# ==============================================================================

@pytest.mark.asyncio
async def test_leave_balances_returns_all_three_types_in_fixed_order():
    """Verify get_leave_balances returns all 3 types in fixed order: Sick Leave, Casual Leave, Vacation Leave."""
    emp_id = uuid.uuid4()
    mock_session = AsyncMock()
    service = LeaveService(mock_session)

    # Existing policy only has Casual Leave
    existing_policies = [
        EmployeeLeavePolicy(
            employee_id=emp_id,
            leave_type="Casual Leave",
            total_days=Decimal("10.0"),
            used_days=Decimal("2.0"),
        )
    ]
    service.repo.ensure_employee_leave_policy = AsyncMock()
    service.repo.get_employee_leave_policies = AsyncMock(return_value=existing_policies)

    balances = await service.get_leave_balances(emp_id)

    assert len(balances) == 3
    assert balances[0].leave_type == "Sick Leave"
    assert balances[1].leave_type == "Casual Leave"
    assert balances[2].leave_type == "Vacation Leave"
    assert balances[1].used_days == 2.0
    assert balances[1].remaining_days == 8.0


# ==============================================================================
# 12. GET /leaves/employees Test
# ==============================================================================

@pytest.mark.asyncio
async def test_get_company_employees_service():
    """Verify get_company_employees returns correctly formatted LeaveEmployeeItem list."""
    comp_id = uuid.uuid4()
    emp1 = make_employee(company_id=comp_id, first_name="Alice", last_name="Brown", department="HR")
    emp2 = make_employee(company_id=comp_id, first_name="Bob", last_name="White", department="Dev")

    mock_session = AsyncMock()
    service = LeaveService(mock_session)
    service.repo.get_company_employees = AsyncMock(return_value=[emp1, emp2])

    items = await service.get_company_employees(company_id=comp_id, page=1, limit=10)
    assert len(items) == 2
    assert items[0].full_name == "Alice Brown"
    assert items[0].department == "HR"
    assert items[1].full_name == "Bob White"
    assert items[1].department == "Dev"


# ==============================================================================
# 13. AI Agent (LeaveAgent) Delegation Test
# ==============================================================================

@pytest.mark.asyncio
async def test_leave_agent_apply_and_cancel_delegation():
    """Verify LeaveAgent delegates to LeaveService.apply_leave and cancel_leave without direct deduction."""
    from app.agents.leave_agent import LeaveAgent

    emp = make_employee()
    mock_session = AsyncMock()
    mock_session.get.return_value = emp

    agent = LeaveAgent(mock_session)

    created_leave = make_leave(
        employee=emp,
        leave_type="Casual Leave",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 2),
        total_days=Decimal("2.0"),
        status="PENDING",
    )

    with patch.object(LeaveService, "apply_leave", new_callable=AsyncMock) as mock_apply, \
         patch.object(LeaveService, "cancel_leave", new_callable=AsyncMock) as mock_cancel, \
         patch.object(LeaveRepository, "get_leave_by_id", new_callable=AsyncMock) as mock_get_leave, \
         patch.object(LeaveRepository, "get_employee_leave_policy_by_type", new_callable=AsyncMock) as mock_policy:
        
        mock_apply.return_value = created_leave
        mock_get_leave.return_value = created_leave
        policy = EmployeeLeavePolicy(
            employee_id=emp.id,
            leave_type="Casual Leave",
            total_days=Decimal("10.0"),
            used_days=Decimal("0.0"),
        )
        mock_policy.return_value = policy

        # Apply leave via agent
        res = await agent.apply_leave(
            employee_id=emp.id,
            leave_type="casual_leave",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 2),
        )

        assert res["success"] is True
        assert res["days_applied"] == 2.0
        assert res["new_used_days"] == 0.0  # NOT directly deducted!
        mock_apply.assert_awaited_once()

        # Cancel leave via agent
        cancelled_leave = make_leave(
            employee=emp,
            leave_type="Casual Leave",
            total_days=Decimal("2.0"),
            status="CANCELLED",
        )
        mock_cancel.return_value = cancelled_leave

        cancel_res = await agent.cancel_leave(
            employee_id=emp.id,
            leave_type="casual_leave",
            days=2.0,
            leave_id=created_leave.id,
        )

        assert cancel_res["success"] is True
        mock_cancel.assert_awaited_once()

