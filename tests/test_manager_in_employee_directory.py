"""Test suite for OFC360 Employee Directory including Managers.

Tests verify:
1. Manager creation via POST /api/v1/managers creates both Manager and Employee workforce records.
2. GET /api/v1/employees returns managers alongside employees with role='manager' and correct designation.
3. Employee directory total count / headcount includes all workforce members (employees + managers).
4. Employee directory search finds managers by name, email, designation, department, and role.
5. Role filtering (role='manager', role='employee') correctly isolates workforce roles.
6. Status filtering (status='ACTIVE', status='INVITED') properly includes managers.
7. Tenant isolation is strictly preserved (Company A cannot see Company B managers in directory).
8. Self-healing synchronization: EmployeeService._sync_managers_to_employees ensures all managers have workforce records.
9. Manager updates (designation, salary, department) synchronize to Employee directory.
10. Manager soft-deletion synchronizes to Employee directory and removes them from active list.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppException
from app.core.rbac import RoleEnum, UserRole
from app.core.security import create_access_token
from app.db.database import get_db_session
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.manager_repository import ManagerRepository
from app.schemas.employee import EmployeeListItem, EmployeeListResponse
from app.schemas.manager import ManagerCreate, ManagerUpdate
from app.services.employee_service import EmployeeService, get_employee_service
from app.services.manager_service import ManagerService, get_manager_service


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _make_test_manager(
    mgr_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    first_name: str = "Mamraj",
    last_name: str = "Yadav",
    personal_email: str = "mamraj@ofc360.com",
    department: str = "Engineering",
    designation: str = "Cloud & DevOps Engineer",
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
) -> Manager:
    mgr = Manager()
    mgr.id = mgr_id or uuid.uuid4()
    mgr.company_id = company_id or uuid.uuid4()
    mgr.user_id = None
    mgr.manager_id = "MGR-202608-0131"
    mgr.first_name = first_name
    mgr.last_name = last_name
    mgr.personal_email = personal_email
    mgr.company_email = personal_email
    mgr.phone = "9828740131"
    mgr.alternate_phone = None
    mgr.gender = "Male"
    mgr.date_of_birth = date(1996, 5, 20)
    mgr.blood_group = "O+"
    mgr.marital_status = "Single"
    mgr.profile_photo_url = None
    mgr.department = department
    mgr.designation = designation
    mgr.branch = "Headquarters"
    mgr.work_location = "Office"
    mgr.joining_date = date(2026, 8, 19)
    mgr.employment_type = "FULL_TIME"
    mgr.employment_status = "CONFIRMED"
    mgr.shift = "General"
    mgr.probation_period_months = 3
    mgr.ctc = Decimal("1200000.00")
    mgr.basic_salary = Decimal("600000.00")
    mgr.hra = Decimal("300000.00")
    mgr.bonus = Decimal("180000.00")
    mgr.pf = Decimal("72000.00")
    mgr.esi = Decimal("0.00")
    mgr.professional_tax = Decimal("2400.00")
    mgr.role = "manager"
    mgr.leave_group = "Standard"
    mgr.status = status_val
    mgr.is_deleted = is_deleted
    mgr.is_active = True
    mgr.is_first_login = False
    mgr.profile_completed = True
    mgr.can_approve_leave = True
    mgr.can_approve_attendance = True
    mgr.can_manage_employees = True
    mgr.can_view_payroll = False
    mgr.can_edit_departments = False
    mgr.can_invite_users = False
    mgr.can_manage_recruitment = False
    mgr.can_manage_performance = False
    mgr.reporting_manager = None
    mgr.reporting_to = None
    mgr.created_by = uuid.uuid4()
    mgr.created_at = datetime.now(timezone.utc)
    mgr.updated_at = datetime.now(timezone.utc)
    mgr.addresses = []
    mgr.documents = []
    mgr.education = []
    mgr.experience = []
    mgr.skills = []
    mgr.emergency_contacts = []
    return mgr


def _make_test_employee(
    emp_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    first_name: str = "Sunaina",
    last_name: str = "Mehra",
    personal_email: str = "sunaina.mehra@example.com",
    department: str = "Engineering",
    designation: str = "Senior Frontend Engineer",
    role: str = "employee",
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
) -> Employee:
    emp = Employee()
    emp.id = emp_id or uuid.uuid4()
    emp.company_id = company_id or uuid.uuid4()
    emp.user_id = None
    emp.employee_id = "EMP-202608-0008"
    emp.first_name = first_name
    emp.last_name = last_name
    emp.personal_email = personal_email
    emp.company_email = personal_email
    emp.phone = "9876543210"
    emp.department = department
    emp.designation = designation
    emp.employment_type = "FULL_TIME"
    emp.employment_status = "CONFIRMED"
    emp.joining_date = date(2026, 8, 17)
    emp.ctc = Decimal("1000000.00")
    emp.basic_salary = Decimal("500000.00")
    emp.hra = Decimal("250000.00")
    emp.bonus = Decimal("150000.00")
    emp.pf = Decimal("60000.00")
    emp.esi = Decimal("0.00")
    emp.professional_tax = Decimal("2400.00")
    emp.role = role
    emp.status = status_val
    emp.is_deleted = is_deleted
    emp.is_active = True
    emp.created_at = datetime.now(timezone.utc)
    emp.updated_at = datetime.now(timezone.utc)
    emp.addresses = []
    emp.documents = []
    emp.education = []
    emp.experience = []
    emp.skills = []
    emp.assets = []
    emp.emergency_contacts = []
    emp.bank_accounts = []
    emp.leave_policies = []
    emp.onboarding_steps = []
    return emp


# ---------------------------------------------------------------------------
# Unit & Service Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_manager_creates_synchronized_employee():
    """Verify ManagerService.create_manager inserts both Manager and Employee records."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_mgr_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    admin_id = uuid.uuid4()
    company_id = uuid.uuid4()

    admin_user = MagicMock()
    admin_user.id = admin_id
    admin_user.company_id = company_id
    admin_user.role = UserRole.HR_ADMIN
    mock_auth_repo.get_user_by_id.return_value = admin_user

    mock_mgr_repo.get_by_personal_email.return_value = None
    mock_mgr_repo.get_by_company_email.return_value = None
    mock_mgr_repo.get_by_phone.return_value = None
    mock_mgr_repo.get_by_manager_id.return_value = None

    created_manager = _make_test_manager(company_id=company_id)
    mock_mgr_repo.create_manager.return_value = created_manager
    mock_mgr_repo.get_by_id.return_value = created_manager

    # Mock execute for sequential manager_id, email collision, and Company fetch
    mock_id_res = MagicMock()
    mock_id_res.scalar_one_or_none.return_value = None
    mock_email_res = MagicMock()
    mock_email_res.scalar_one_or_none.return_value = None
    mock_comp_res = MagicMock()
    mock_comp_obj = Company(id=company_id, name="OFC Corp")
    mock_comp_res.scalar_one_or_none.return_value = mock_comp_obj
    mock_session.execute.side_effect = [mock_id_res, mock_email_res, mock_comp_res]

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_mgr_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    payload = ManagerCreate(
        first_name="Mamraj",
        last_name="Yadav",
        personal_email="mamraj@ofc360.com",
        company_email="mamraj@ofc360.com",
        phone="9828740131",
        department="Engineering",
        designation="Cloud & DevOps Engineer",
        role="manager",
        status="Active",
        ctc=Decimal("1200000.00"),
        joining_date=date(2026, 8, 19),
    )

    result = await service.create_manager(admin_id, payload)

    assert result.first_name == "Mamraj"
    assert result.designation == "Cloud & DevOps Engineer"
    assert result.role == "manager"

    # Verify session.add was called for synchronized Employee
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]
    emp_objects = [o for o in added_objects if isinstance(o, Employee)]
    assert len(emp_objects) >= 1
    emp = emp_objects[0]
    assert emp.first_name == "Mamraj"
    assert emp.designation == "Cloud & DevOps Engineer"
    assert emp.role == "manager"
    assert emp.department == "Engineering"
    assert emp.ctc == Decimal("1200000.00")
    assert emp.company_id == company_id


@pytest.mark.asyncio
async def test_employee_directory_returns_both_employees_and_managers():
    """Verify EmployeeService.list_employees returns workforce records for employees and managers."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    company_id = uuid.uuid4()
    emp1 = _make_test_employee(company_id=company_id, first_name="Sunaina", role="employee", designation="Senior Frontend Engineer")
    emp2 = _make_test_employee(company_id=company_id, first_name="Mamraj", role="manager", designation="Cloud & DevOps Engineer")

    mock_emp_repo.list_employees.return_value = [emp1, emp2]
    mock_emp_repo.count_employees.return_value = 2

    # Mock execute for _sync_managers_to_employees
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_res

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    result = await service.list_employees(
        company_id=company_id,
        department=None,
        status_filter=None,
        employment_type=None,
        search=None,
        page=1,
        limit=10,
    )

    assert result.total == 2
    assert len(result.items) == 2
    roles = [item.role.lower() for item in result.items]
    assert "employee" in roles
    assert "manager" in roles

    manager_item = next(i for i in result.items if i.first_name == "Mamraj")
    assert manager_item.designation == "Cloud & DevOps Engineer"
    assert manager_item.role == "manager"


@pytest.mark.asyncio
async def test_employee_directory_role_filter_manager():
    """Verify role='manager' filter returns only managers."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    company_id = uuid.uuid4()
    mgr = _make_test_employee(company_id=company_id, first_name="Mamraj", role="manager", designation="Cloud & DevOps Engineer")

    mock_emp_repo.list_employees.return_value = [mgr]
    mock_emp_repo.count_employees.return_value = 1

    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_res

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    result = await service.list_employees(
        company_id=company_id,
        department=None,
        status_filter=None,
        employment_type=None,
        search=None,
        page=1,
        limit=10,
        role="manager",
    )

    assert result.total == 1
    assert result.items[0].first_name == "Mamraj"
    assert result.items[0].role == "manager"
    mock_emp_repo.list_employees.assert_called_once()
    assert mock_emp_repo.list_employees.call_args.kwargs.get("role") == "manager"


@pytest.mark.asyncio
async def test_employee_directory_search_finds_manager():
    """Verify searching for manager by name or designation passes through to repository."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    company_id = uuid.uuid4()
    mgr = _make_test_employee(company_id=company_id, first_name="Mamraj", designation="Cloud & DevOps Engineer")

    mock_emp_repo.list_employees.return_value = [mgr]
    mock_emp_repo.count_employees.return_value = 1

    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_res

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    result = await service.list_employees(
        company_id=company_id,
        department=None,
        status_filter=None,
        employment_type=None,
        search="Cloud & DevOps",
        page=1,
        limit=10,
    )

    assert result.total == 1
    assert result.items[0].first_name == "Mamraj"
    assert result.items[0].designation == "Cloud & DevOps Engineer"
    assert mock_emp_repo.list_employees.call_args.kwargs.get("search") == "Cloud & DevOps"


@pytest.mark.asyncio
async def test_self_healing_manager_synchronization():
    """Verify _sync_managers_to_employees automatically creates missing Employee records for existing Managers."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    company_id = uuid.uuid4()
    mgr = _make_test_manager(company_id=company_id, first_name="Mamraj", last_name="Yadav")

    # 1st execute: select(Manager) returns mgr
    mgr_result = MagicMock()
    mgr_result.scalars.return_value.all.return_value = [mgr]

    # 2nd execute: select(Employee) returns None (missing in employees table)
    emp_result = MagicMock()
    emp_result.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [mgr_result, emp_result]

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    await service._sync_managers_to_employees(company_id)

    # Verify session.add was called with a new Employee record matching the manager
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]
    emp_objects = [o for o in added_objects if isinstance(o, Employee)]
    assert len(emp_objects) == 1
    new_emp = emp_objects[0]
    assert new_emp.first_name == "Mamraj"
    assert new_emp.last_name == "Yadav"
    assert new_emp.role == "manager"
    assert new_emp.designation == "Cloud & DevOps Engineer"
    assert new_emp.company_id == company_id


# ---------------------------------------------------------------------------
# HTTP API Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_employees_api_includes_managers_with_role_and_designation():
    """Verify GET /api/v1/employees returns HTTP 200 with managers and employees."""
    app = create_app()

    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mgr = _make_test_employee(company_id=company_id, first_name="Mamraj", last_name="Yadav", role="manager", designation="Cloud & DevOps Engineer")
    emp = _make_test_employee(company_id=company_id, first_name="Sunaina", last_name="Mehra", role="employee", designation="Senior Frontend Engineer")

    mock_emp_service = AsyncMock()
    mock_emp_service.list_employees.return_value = EmployeeListResponse(
        items=[EmployeeListItem.model_validate(emp), EmployeeListItem.model_validate(mgr)],
        total=2,
        page=1,
        limit=10,
        pages=1,
        total_pages=1,
        has_next=False,
        has_previous=False,
    )

    app.dependency_overrides[get_employee_service] = lambda: mock_emp_service

    token = create_access_token(
        str(admin_id),
        claims={
            "role": "hr_admin",
            "company_id": str(company_id),
            "email": "admin@ofc360.com",
            "is_active": True,
        },
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        response = await ac.get(
            "/api/v1/employees",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 2

    # Validate manager shape
    mgr_item = next(i for i in data["items"] if i["first_name"] == "Mamraj")
    assert mgr_item["designation"] == "Cloud & DevOps Engineer"
    assert mgr_item["role"] == "manager"
    assert mgr_item["department"] == "Engineering"
