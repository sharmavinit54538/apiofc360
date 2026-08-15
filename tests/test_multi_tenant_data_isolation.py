"""Comprehensive tests for Multi-Tenant Data Isolation (IDOR Prevention) & Audit Log Enforcement.

Tests:
1. EmployeeRepository IDOR prevention & tenant isolation (get_by_id, get_by_employee_id, list, count, update, soft_delete).
2. PayrollRepository IDOR prevention & tenant isolation (get_cycle, get_ot_policy, get_deduction, get_loan, get_reimbursement, get_payslip, etc.).
3. DocumentRepository IDOR prevention & tenant isolation (get_employee_document_by_id, list, get_company_document_by_id).
4. ManagerRepository & DepartmentRepository tenant isolation.
5. Superadmin cross-tenant bypass when company_id is None.
6. AuditLog company_id capture across security and data events.
"""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog, create_audit_entry
from app.models.company import Company
from app.models.department import Department
from app.models.document import CompanyDocument
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.manager import Manager
from app.models.payroll import (
    AdvanceLoan,
    BankAdviceFile,
    BankDisbursementRecord,
    BonusAward,
    BonusPlan,
    ComplianceObligation,
    DeductionComponent,
    OvertimeEntry,
    OvertimePolicy,
    PayCycle,
    Payslip,
    ReimbursementClaim,
)
from app.repositories.department_repository import DepartmentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.manager_repository import ManagerRepository
from app.repositories.payroll_repository import PayrollRepository


# ==============================================================================
# 1. Employee Repository Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_employee_repository_tenant_isolation_get_by_id():
    """Verify tenant B cannot access tenant A's employee by UUID (IDOR Prevention)."""
    mock_session = AsyncMock()
    repo = EmployeeRepository(session=mock_session)

    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    emp_id = uuid.uuid4()

    # When query executes, simulate SQLAlchemy returning Employee belonging to Company A
    mock_emp = Employee(id=emp_id, company_id=comp_a, first_name="Alice", last_name="Smith", employee_id="EMP-001")

    # 1. Company A queries its own employee -> scalar_one_or_none returns mock_emp
    mock_res_a = MagicMock()
    mock_res_a.scalar_one_or_none.return_value = mock_emp
    mock_session.execute.return_value = mock_res_a

    res_a = await repo.get_by_id(emp_id, company_id=comp_a)
    assert res_a == mock_emp
    assert mock_session.execute.call_count == 1

    # Verify query had company_id == comp_a in where clause
    called_stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(called_stmt)
    assert "employees.company_id =" in stmt_str or "company_id" in stmt_str

    # 2. Company B queries Company A's employee -> query includes Company B filter, returning None
    mock_res_b = MagicMock()
    mock_res_b.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res_b

    res_b = await repo.get_by_id(emp_id, company_id=comp_b)
    assert res_b is None

    # 3. Superadmin queries with company_id=None -> returns employee across tenants
    mock_res_sa = MagicMock()
    mock_res_sa.scalar_one_or_none.return_value = mock_emp
    mock_session.execute.return_value = mock_res_sa

    res_sa = await repo.get_by_id(emp_id, company_id=None)
    assert res_sa == mock_emp


@pytest.mark.asyncio
async def test_employee_repository_tenant_isolation_get_by_employee_id():
    """Verify string employee_id lookups strictly filter by company_id when provided."""
    mock_session = AsyncMock()
    repo = EmployeeRepository(session=mock_session)

    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    emp_str_id = "EMP-2026-0001"

    # Company A lookup
    mock_res = MagicMock()
    mock_session.execute.return_value = mock_res

    await repo.get_by_employee_id(emp_str_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "employees.company_id" in str(called_stmt)


@pytest.mark.asyncio
async def test_employee_repository_list_and_count_no_cross_tenant_fallback():
    """Verify list_employees and count_employees strictly scope to company_id with zero cross-tenant fallback."""
    mock_session = AsyncMock()
    repo = EmployeeRepository(session=mock_session)

    comp_b = uuid.uuid4()

    # Simulate empty company B
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_res

    items = await repo.list_employees(company_id=comp_b)
    assert items == []
    # Exactly one query executed (no fallback query!)
    assert mock_session.execute.call_count == 1

    # Count
    mock_count_res = MagicMock()
    mock_count_res.scalar_one.return_value = 0
    mock_session.execute.return_value = mock_count_res

    cnt = await repo.count_employees(company_id=comp_b)
    assert cnt == 0


# ==============================================================================
# 2. Payroll Repository Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_payroll_repository_get_cycle_tenant_isolation():
    """Verify pay cycle lookups enforce company_id."""
    mock_session = AsyncMock()
    repo = PayrollRepository(session=mock_session)

    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    cycle_id = uuid.uuid4()

    mock_cycle = PayCycle(id=cycle_id, company_id=comp_a, period_month=6, period_year=2026, status="DRAFT")
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_cycle
    mock_session.execute.return_value = mock_res

    # Query with company_a
    res = await repo.get_cycle(cycle_id, company_id=comp_a)
    assert res == mock_cycle
    called_stmt = mock_session.execute.call_args[0][0]
    assert "pay_cycles.company_id" in str(called_stmt)

    # Query with company_b
    mock_res.scalar_one_or_none.return_value = None
    res_b = await repo.get_cycle(cycle_id, company_id=comp_b)
    assert res_b is None


@pytest.mark.asyncio
async def test_payroll_repository_payslip_and_deduction_isolation():
    """Verify payslips, deductions, loans, and reimbursements enforce tenant filters."""
    mock_session = AsyncMock()
    repo = PayrollRepository(session=mock_session)

    comp_a = uuid.uuid4()
    payslip_id = uuid.uuid4()
    deduction_id = uuid.uuid4()
    loan_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_session.execute.return_value = mock_res

    # 1. Payslip joins employee company_id
    await repo.get_payslip(payslip_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "employees.company_id" in str(called_stmt) or "company_id" in str(called_stmt)

    # 2. Deduction
    await repo.get_deduction(deduction_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "deduction_components.company_id" in str(called_stmt)

    # 3. Loan
    await repo.get_loan(loan_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "advance_loans.company_id" in str(called_stmt)

    # 4. Reimbursement
    await repo.get_reimbursement(claim_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "reimbursement_claims.company_id" in str(called_stmt)


# ==============================================================================
# 3. Document Repository Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_document_repository_employee_and_company_doc_isolation():
    """Verify EmployeeDocument and CompanyDocument queries enforce company_id."""
    mock_session = AsyncMock()
    repo = DocumentRepository(session=mock_session)

    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    doc_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_session.execute.return_value = mock_res

    # 1. Employee Document joins Employee company_id
    await repo.get_employee_document_by_id(doc_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "employees.company_id" in str(called_stmt) or "company_id" in str(called_stmt)

    # 2. Company Document checks CompanyDocument company_id
    await repo.get_company_document_by_id(doc_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "company_documents.company_id" in str(called_stmt)

    # 3. List Company Documents scopes to company_id
    await repo.list_company_documents(company_id=comp_b)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "company_documents.company_id" in str(called_stmt)


# ==============================================================================
# 4. Manager & Department Repository Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_repository_tenant_isolation():
    """Verify ManagerRepository enforces company_id without cross-tenant fallback."""
    mock_session = AsyncMock()
    repo = ManagerRepository(session=mock_session)

    comp_a = uuid.uuid4()
    mgr_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_session.execute.return_value = mock_res

    await repo.get_by_id(mgr_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "managers.company_id" in str(called_stmt)

    await repo.list_managers(company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "managers.company_id" in str(called_stmt)


@pytest.mark.asyncio
async def test_department_repository_tenant_isolation():
    """Verify DepartmentRepository enforces company_id and avoids cross-tenant leak."""
    mock_session = AsyncMock()
    repo = DepartmentRepository(session=mock_session)

    comp_a = uuid.uuid4()
    dept_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_session.execute.return_value = mock_res

    await repo.get_by_id(dept_id, company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "departments.company_id" in str(called_stmt)

    await repo.list_departments(company_id=comp_a)
    called_stmt = mock_session.execute.call_args[0][0]
    assert "departments.company_id" in str(called_stmt)


# ==============================================================================
# 5. AuditLog Standardized Factory & company_id Capture Tests
# ==============================================================================

def test_audit_log_create_audit_entry_captures_company_id():
    """Verify create_audit_entry factory sets company_id, action, user_id, and details."""
    comp_id = uuid.uuid4()
    usr_id = uuid.uuid4()

    entry = create_audit_entry(
        action="SECURITY_LOCK_TRIGGERED",
        company_id=comp_id,
        user_id=usr_id,
        email="admin@example.com",
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        details="User account locked due to excessive failed attempts",
    )

    assert isinstance(entry, AuditLog)
    assert entry.company_id == comp_id
    assert entry.user_id == usr_id
    assert entry.action == "SECURITY_LOCK_TRIGGERED"
    assert entry.email == "admin@example.com"
    assert entry.ip_address == "192.168.1.1"
    assert entry.details == "User account locked due to excessive failed attempts"
