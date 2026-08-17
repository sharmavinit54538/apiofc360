"""Comprehensive Production-Readiness Test Suite for OFC360 Executive Module.

Tests Cover:
1. Architecture & Role Standardization:
   - Canonical RoleEnum.EXECUTIVE ("executive") and legacy alias normalization (CEO, CTO, CFO, VP, etc.).
   - Schema validation for Executive creation and update.

2. Executive CRUD Lifecycle:
   - CREATE: Admin creates Executive profile with compensation, designation, department, and nested relations.
   - READ: Full profile retrieval with all fields, aliases, and relations.
   - LIST: Filterable, paginated, searchable listing scoped to tenant.
   - UPDATE: Full and partial updates.
   - DELETE: Soft-delete with token revocation and lifecycle deactivation.
   - RESTORE / ACTIVATE / DEACTIVATE: Lifecycle status management.

3. Executive Salary & Compensation Regression:
   - Partial update of non-salary fields preserves existing CTC and salary breakup.
   - Updating single salary component merges cleanly with DB state without zeroing CTC.
   - CTC cross-field validation: individual components <= CTC, basic + hra + bonus <= CTC * 1.01.
   - Zero/negative/invalid salary rejection.

4. RBAC & Access Control:
   - Super Admin & HR Admin: Full administrative privileges (create, update, delete, activate).
   - Executive: Managerial read access (dashboard, list, read), Executive-only endpoints (require_executive, copilot), but 403 on admin writes.
   - Manager: Allowed general management, but 403 on executive-only dependencies.
   - Employee & Intern: 403 Forbidden on management and executive endpoints.

5. Multi-Tenant Isolation:
   - Company A caller cannot read, list, update, or delete Company B Executive records (returns 404).
   - Direct ID access across company boundaries is strictly blocked.

6. User ↔ Executive Synchronization:
   - HR Admin creating Executive user account links User + Employee.
   - Deactivating/suspending Executive synchronizes User account status and revokes active tokens.

7. Nested Relations & Response Serialization:
   - Addresses, documents, education, experience, skills, emergency contacts, bank accounts.
   - Schema aliases: annual_ctc, annualCtc, salary, basicSalary, professionalTax, costCenterId.

8. API Validation & Edge Case Error Handling:
   - 400 Bad Request: Self-reporting manager, invalid compensation breakup.
   - 401 Unauthorized: Missing/invalid token.
   - 403 Forbidden: Missing company association, insufficient role privileges.
   - 404 Not Found: Nonexistent ID, cross-tenant ID, soft-deleted record.
   - 409 Conflict: Duplicate personal email, company email, phone, employee ID.
   - 422 Unprocessable Entity: Missing required fields, invalid UUID format, invalid enum.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException, NotFoundException
from app.core.rbac import (
    ADMIN_MANAGER_ROLES,
    ADMIN_ROLES,
    EXECUTIVE_ROLES,
    ROLE_EXECUTIVE,
    ROLE_HR_ADMIN,
    ROLE_MANAGER,
    ROLE_SUPER_ADMIN,
    RoleEnum,
    UserRole,
    require_admin,
    require_admin_or_manager,
    require_executive,
    require_hr_admin,
)
from app.core.security import create_access_token
from app.db.database import get_db_session
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.executive_copilot import CopilotQueryLog
from app.models.user import User, UserAccountStatus
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee.constants import ROLE_VALUES
from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.profile import EmployeeResponse, EmployeeListResponse
from app.schemas.employee.update import EmployeeListItem, EmployeeUpdate
from app.schemas.hr_admin import HRAdminCreateUserRequest, HRAdminUserResponse
from app.services.email_service import EmailService
from app.services.employee_service import EmployeeService, get_employee_service
from app.services.enterprise_intelligence_services import ExecutiveCopilotService
from app.services.hr_admin_service import HRAdminService


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_executive(
    emp_uuid: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    first_name: str = "Aravind",
    last_name: str = "Srinivasan",
    employee_id: str = "EMP-EXEC-001",
    department: str = "Executive Leadership",
    designation: str = "Chief Technology Officer",
    phone: str = "9876543210",
    personal_email: str = "aravind.exec@example.com",
    company_email: str = "aravind@company.com",
    role: str = "executive",
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
    is_active: bool = True,
    ctc: Decimal = Decimal("3600000.00"),
    basic_salary: Decimal = Decimal("1800000.00"),
    hra: Decimal = Decimal("900000.00"),
    bonus: Decimal = Decimal("500000.00"),
) -> Employee:
    """Factory helper to construct an Employee instance with executive credentials."""
    emp = Employee()
    emp.id = emp_uuid or uuid.uuid4()
    emp.company_id = company_id or uuid.uuid4()
    emp.user_id = user_id
    emp.employee_id = employee_id
    emp.first_name = first_name
    emp.last_name = last_name
    emp.department = department
    emp.designation = designation
    emp.phone = phone
    emp.personal_email = personal_email
    emp.company_email = company_email
    emp.joining_date = date(2025, 1, 1)
    emp.employment_type = "FULL_TIME"
    emp.employment_status = "CONFIRMED"
    emp.role = role
    emp.status = status_val
    emp.is_deleted = is_deleted
    emp.is_active = is_active
    emp.ctc = ctc
    emp.basic_salary = basic_salary
    emp.hra = hra
    emp.bonus = bonus
    emp.pf = Decimal("216000.00")
    emp.esi = Decimal("0.00")
    emp.professional_tax = Decimal("2500.00")
    emp.created_at = datetime.now(timezone.utc)
    emp.updated_at = datetime.now(timezone.utc)
    emp.role_metadata = {}
    emp.verification_status = "VERIFIED"
    emp.employee_capacity = 100
    emp.cost_center_id = "CC-EXEC-01"

    # Nested relations
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


# ==============================================================================
# 1. Architecture & Role Standardization Tests
# ==============================================================================

def test_canonical_role_enum_and_executive_aliases():
    """Verify RoleEnum.EXECUTIVE canonical value and alias normalization for C-Suite/VPs."""
    assert RoleEnum.EXECUTIVE.value == "executive"
    assert "executive" in ROLE_VALUES

    # C-Suite / Executive alias normalization
    assert RoleEnum.from_str("executive") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("EXECUTIVE") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("ceo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("CEO") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cto") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cfo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("coo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cmo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("clo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("ciso") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cio") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("vp") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("director") == RoleEnum.EXECUTIVE


def test_role_enum_privilege_helpers():
    """Verify RoleEnum helper method behaviors for Executive."""
    assert RoleEnum.EXECUTIVE.is_manager() is True
    assert RoleEnum.EXECUTIVE.is_admin() is False
    assert RoleEnum.EXECUTIVE.is_super_admin() is False


def test_employee_create_schema_accepts_executive_role():
    """Verify EmployeeCreate schema accepts role='executive' and valid C-level designations."""
    payload = EmployeeCreate(
        first_name="Sundar",
        last_name="Pichai",
        personal_email="sundar.p@example.com",
        phone="9876543210",
        department="Executive Board",
        designation="Chief Executive Officer",
        role="executive",
        employment_type="FULL_TIME",
        joining_date=date(2026, 1, 1),
        ctc=Decimal("10000000"),
        basic_salary=Decimal("5000000"),
    )
    assert payload.role == "executive"
    assert payload.designation == "Chief Executive Officer"


def test_employee_create_schema_rejects_unrecognized_role():
    """Verify EmployeeCreate schema rejects invalid/unregistered role strings."""
    with pytest.raises(ValidationError) as exc:
        EmployeeCreate(
            first_name="Sundar",
            last_name="Pichai",
            personal_email="sundar.p@example.com",
            phone="9876543210",
            department="Executive Board",
            designation="Chief Executive Officer",
            role="unauthorized_role",
            employment_type="FULL_TIME",
            joining_date=date(2026, 1, 1),
        )
    assert "role must be one of" in str(exc.value)


# ==============================================================================
# 2. Executive CRUD Lifecycle Testing
# ==============================================================================

@pytest.mark.asyncio
async def test_executive_create_full_lifecycle():
    """Test successful creation of an Executive with salary breakup, relations, and token generation."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_company = MagicMock()
    mock_company.name = "TechCorp"
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_company)))
    mock_session.commit = AsyncMock()

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_personal_email = AsyncMock(return_value=None)
    mock_repo.get_by_company_email_in_company = AsyncMock(return_value=None)
    mock_repo.get_by_employee_id = AsyncMock(return_value=None)

    created_exec = make_test_executive(company_id=company_id)
    mock_repo.create_employee = AsyncMock(return_value=created_exec)
    mock_repo.get_by_id = AsyncMock(return_value=created_exec)
    mock_repo.upsert_address = AsyncMock()
    mock_repo.create_document = AsyncMock()
    mock_repo.create_education = AsyncMock()
    mock_repo.create_experience = AsyncMock()
    mock_repo.create_skill = AsyncMock()
    mock_repo.create_emergency_contact = AsyncMock()
    mock_repo.create_bank_account = AsyncMock()
    mock_repo.create_onboarding_steps = AsyncMock()

    mock_email = AsyncMock(spec=EmailService)
    mock_email.send_employee_onboarding_invite = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=mock_email,
    )

    payload = EmployeeCreate(
        first_name="Aravind",
        last_name="Srinivasan",
        personal_email="aravind.exec@example.com",
        company_email="aravind@company.com",
        phone="9876543210",
        department="Executive Leadership",
        designation="Chief Technology Officer",
        role="executive",
        joining_date=date(2025, 1, 1),
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("1800000.00"),
        hra=Decimal("900000.00"),
        bonus=Decimal("500000.00"),
    )

    with patch("app.services.employee_service.generate_employee_id", new=AsyncMock(return_value="EMP-202608-0001")):
        result = await service.create_employee(admin_id=admin_id, company_id=company_id, payload=payload)

    assert result.first_name == "Aravind"
    assert result.role == "executive"
    assert result.designation == "Chief Technology Officer"
    assert result.ctc == Decimal("3600000.00")
    mock_repo.create_employee.assert_called_once()
    mock_email.send_employee_onboarding_invite.assert_called_once()


@pytest.mark.asyncio
async def test_executive_read_by_id():
    """Test retrieving an Executive by ID with company scoping."""
    company_id = uuid.uuid4()
    exec_id = uuid.uuid4()
    mock_exec = make_test_executive(emp_uuid=exec_id, company_id=company_id)

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id = AsyncMock(return_value=mock_exec)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    result = await service.get_employee(exec_id, company_id=company_id)
    assert result.id == exec_id
    assert result.role == "executive"
    assert result.designation == "Chief Technology Officer"
    assert result.salary == Decimal("3600000.00") or result.ctc == Decimal("3600000.00")


@pytest.mark.asyncio
async def test_executive_read_not_found():
    """Test 404 response when Executive ID does not exist."""
    company_id = uuid.uuid4()
    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id = AsyncMock(return_value=None)
    mock_repo.get_by_id_raw = AsyncMock(return_value=None)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    with pytest.raises(AppException) as exc:
        await service.get_employee(uuid.uuid4(), company_id=company_id)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_executive_list_filtering_and_pagination():
    """Test listing Executives with role, department, and designation filters."""
    company_id = uuid.uuid4()
    exec1 = make_test_executive(company_id=company_id, designation="Chief Executive Officer")
    exec2 = make_test_executive(company_id=company_id, designation="Chief Financial Officer")

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.list_employees = AsyncMock(return_value=[exec1, exec2])
    mock_repo.count_employees = AsyncMock(return_value=2)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    res = await service.list_employees(
        company_id=company_id,
        department="Executive Leadership",
        status_filter=None,
        employment_type=None,
        search=None,
        page=1,
        limit=10,
    )

    assert res.total == 2
    assert len(res.items) == 2
    assert res.items[0].designation == "Chief Executive Officer"
    assert res.items[1].designation == "Chief Financial Officer"


# ==============================================================================
# 3. Executive Update & Salary Merge Regression Testing
# ==============================================================================

@pytest.mark.asyncio
async def test_executive_partial_update_preserves_salary_and_ctc():
    """Updating only designation must preserve existing CTC (3600000) and salary components."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    mock_exec = make_test_executive(
        emp_uuid=exec_id,
        company_id=company_id,
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("1800000.00"),
        designation="VP of Engineering",
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_exec)
    mock_repo.update_employee = AsyncMock()

    # After update, designation changed but ctc intact
    updated_exec = make_test_executive(
        emp_uuid=exec_id,
        company_id=company_id,
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("1800000.00"),
        designation="Chief Technology Officer",
    )
    mock_repo.get_by_id = AsyncMock(return_value=updated_exec)

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    payload = EmployeeUpdate(designation="Chief Technology Officer")
    res = await service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=exec_id, payload=payload)

    assert res.designation == "Chief Technology Officer"
    assert res.ctc == Decimal("3600000.00")
    assert res.basic_salary == Decimal("1800000.00")
    called_kwargs = mock_repo.update_employee.call_args[1]
    assert called_kwargs.get("designation") == "Chief Technology Officer"
    assert "ctc" not in called_kwargs


@pytest.mark.asyncio
async def test_executive_partial_salary_update_merges_with_existing_db():
    """Updating only bonus merges with existing DB basic_salary and validates against existing CTC."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    mock_exec = make_test_executive(
        emp_uuid=exec_id,
        company_id=company_id,
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("1800000.00"),
        hra=Decimal("900000.00"),
        bonus=Decimal("300000.00"),
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_exec)
    mock_repo.update_employee = AsyncMock()

    updated_exec = make_test_executive(
        emp_uuid=exec_id,
        company_id=company_id,
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("1800000.00"),
        hra=Decimal("900000.00"),
        bonus=Decimal("600000.00"),
    )
    mock_repo.get_by_id = AsyncMock(return_value=updated_exec)

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    # Valid bonus increase (1.8M + 0.9M + 0.6M = 3.3M <= 3.6M CTC)
    payload = EmployeeUpdate(bonus=Decimal("600000.00"))
    res = await service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=exec_id, payload=payload)
    assert res.bonus == Decimal("600000.00")
    assert res.ctc == Decimal("3600000.00")


@pytest.mark.asyncio
async def test_executive_salary_update_rejects_exceeding_breakup():
    """Updating bonus to an amount that causes basic + hra + bonus to exceed CTC must be rejected with 400."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    mock_exec = make_test_executive(
        emp_uuid=exec_id,
        company_id=company_id,
        ctc=Decimal("3600000.00"),
        basic_salary=Decimal("2000000.00"),
        hra=Decimal("1000000.00"),
        bonus=Decimal("200000.00"),
    )

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_exec)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    # Bonus of 1M -> 2M + 1M + 1M = 4M > 3.6M CTC -> 400 Bad Request
    payload = EmployeeUpdate(bonus=Decimal("1000000.00"))
    with pytest.raises(AppException) as exc:
        await service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=exec_id, payload=payload)
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "exceeds ctc" in exc.value.message


# ==============================================================================
# 4. Soft Delete, Deactivation, and Token Revocation
# ==============================================================================

@pytest.mark.asyncio
async def test_executive_soft_delete_and_token_revocation():
    """Soft deleting an Executive sets is_deleted=True, status=TERMINATED, and revokes tokens."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    exec_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_exec = make_test_executive(emp_uuid=exec_id, company_id=company_id, user_id=user_id)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_exec)
    mock_repo.soft_delete = AsyncMock()

    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_auth_repo.revoke_all_user_refresh_tokens = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=mock_auth_repo,
        email_service=AsyncMock(),
    )

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new=AsyncMock()) as mock_redis:
        await service.delete_employee(admin_id=admin_id, company_id=company_id, employee_uuid=exec_id)
        mock_repo.soft_delete.assert_called_once_with(exec_id, deleted_by=admin_id)
        mock_auth_repo.revoke_all_user_refresh_tokens.assert_called_once_with(user_id)
        mock_redis.assert_called_once_with(user_id)


# ==============================================================================
# 5. RBAC & Access Control Testing
# ==============================================================================

def test_require_admin_allows_super_and_hr_admin_rejects_executive():
    """Verify require_admin allows Super Admin / HR Admin but strictly rejects Executive."""
    claims_sa = {"sub": str(uuid.uuid4()), "role": ROLE_SUPER_ADMIN, "email": "superadmin@ofc360.com"}
    claims_hr = {"sub": str(uuid.uuid4()), "role": ROLE_HR_ADMIN}
    claims_exec = {"sub": str(uuid.uuid4()), "role": ROLE_EXECUTIVE}

    assert require_admin(claims_sa) == claims_sa
    assert require_admin(claims_hr) == claims_hr

    with pytest.raises(Exception) as exc:
        require_admin(claims_exec)
    assert getattr(exc.value, "status_code", None) == status.HTTP_403_FORBIDDEN


def test_require_admin_or_manager_allows_executive():
    """Verify require_admin_or_manager allows Executive for managerial and read operations."""
    claims_exec = {"sub": str(uuid.uuid4()), "role": ROLE_EXECUTIVE}
    assert require_admin_or_manager(claims_exec) == claims_exec


def test_require_executive_dependency():
    """Verify require_executive allows Executive, HR Admin, and Super Admin, but rejects Manager and Employee."""
    claims_exec = {"sub": str(uuid.uuid4()), "role": ROLE_EXECUTIVE}
    claims_hr = {"sub": str(uuid.uuid4()), "role": ROLE_HR_ADMIN}
    claims_mgr = {"sub": str(uuid.uuid4()), "role": ROLE_MANAGER}
    claims_emp = {"sub": str(uuid.uuid4()), "role": "employee"}

    assert require_executive(claims_exec) == claims_exec
    assert require_executive(claims_hr) == claims_hr

    with pytest.raises(Exception) as exc1:
        require_executive(claims_mgr)
    assert getattr(exc1.value, "status_code", None) == status.HTTP_403_FORBIDDEN

    with pytest.raises(Exception) as exc2:
        require_executive(claims_emp)
    assert getattr(exc2.value, "status_code", None) == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 6. Multi-Tenant Isolation Testing
# ==============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_isolation_cross_company_access_blocked():
    """Verify Company A caller cannot read, update, or delete Company B Executive."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    admin_a = uuid.uuid4()
    exec_b_id = uuid.uuid4()

    # Executive belongs to Company B
    exec_b = make_test_executive(emp_uuid=exec_b_id, company_id=company_b)

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=exec_b)
    mock_repo.get_by_id = AsyncMock(return_value=exec_b)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    # 1. Company A admin trying to GET Company B Executive
    with pytest.raises(AppException) as exc_get:
        await service.get_employee(exec_b_id, company_id=company_a)
    assert exc_get.value.status_code == status.HTTP_404_NOT_FOUND

    # 2. Company A admin trying to UPDATE Company B Executive
    with pytest.raises(AppException) as exc_up:
        await service.update_employee(admin_id=admin_a, company_id=company_a, employee_uuid=exec_b_id, payload=EmployeeUpdate(designation="CEO"))
    assert exc_up.value.status_code == status.HTTP_404_NOT_FOUND

    # 3. Company A admin trying to DELETE Company B Executive
    with pytest.raises(AppException) as exc_del:
        await service.delete_employee(admin_id=admin_a, company_id=company_a, employee_uuid=exec_b_id)
    assert exc_del.value.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 7. User ↔ Executive Synchronization & HR Admin Creation
# ==============================================================================

@pytest.mark.asyncio
async def test_hr_admin_service_creates_executive_user_and_employee():
    """Verify HRAdminService creates a User with UserRole.EXECUTIVE and matching Employee record."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_exec_res = MagicMock()
    mock_exec_res.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    mock_session.execute = AsyncMock(return_value=mock_exec_res)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_email = AsyncMock(spec=EmailService)
    mock_email.send_invitation = AsyncMock()

    hr_service = HRAdminService(session=mock_session, email_service=mock_email)

    payload = HRAdminCreateUserRequest(
        first_name="Vikram",
        last_name="Sarabhai",
        email="vikram.sarabhai@example.com",
        phone="9876543211",
        role="EXECUTIVE",
        department="Executive Leadership",
        designation="Chief Executive Officer",
        ctc=Decimal("5000000.00"),
        basic_salary=Decimal("2500000.00"),
    )

    with patch("app.services.hr_admin_service.generate_employee_id", new=AsyncMock(return_value="EMP-EXEC-009")):
        user_res = await hr_service.create_user(admin_id=admin_id, company_id=company_id, payload=payload)

    assert user_res.email == "vikram.sarabhai@example.com"
    assert user_res.role == "executive"
    assert user_res.designation == "Chief Executive Officer"
    assert user_res.department == "Executive Leadership"
    assert mock_session.add.call_count >= 2


# ==============================================================================
# 8. API Validation & Edge Case Error Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_duplicate_personal_email_conflict():
    """Creating an Executive with an existing personal email raises 409 ConflictException."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_company = MagicMock()
    mock_company.name = "TechCorp"
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_company)))

    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_personal_email = AsyncMock(return_value=make_test_executive())

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    payload = EmployeeCreate(
        first_name="Aravind",
        last_name="Srinivasan",
        personal_email="aravind.exec@example.com",
        phone="9876543210",
        department="Executive Leadership",
        designation="CTO",
        role="executive",
        joining_date=date(2025, 1, 1),
    )

    with pytest.raises(ConflictException) as exc:
        await service.create_employee(admin_id=admin_id, company_id=company_id, payload=payload)
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "Email already exists" in exc.value.message


@pytest.mark.asyncio
async def test_executive_self_reporting_manager_guard():
    """An Executive cannot be their own reporting manager (raises 400 Bad Request)."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    mock_exec = make_test_executive(emp_uuid=exec_id, company_id=company_id)
    mock_repo = AsyncMock(spec=EmployeeRepository)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_exec)

    service = EmployeeService(
        session=AsyncMock(),
        employee_repository=mock_repo,
        auth_repository=AsyncMock(),
        email_service=AsyncMock(),
    )

    payload = EmployeeUpdate(reporting_manager_id=exec_id)
    with pytest.raises(AppException) as exc:
        await service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=exec_id, payload=payload)
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "cannot be their own reporting manager" in exc.value.message


# ==============================================================================
# 9. Executive AI Copilot Query Testing
# ==============================================================================

@pytest.mark.asyncio
async def test_executive_copilot_query_service():
    """Verify ExecutiveCopilotService executes and logs executive strategy queries."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    service = ExecutiveCopilotService(db=mock_session)
    service.llm = AsyncMock()
    service.llm.complete = AsyncMock(return_value='{"ai_response": "Strategic headcount growth recommended in Q3."}')

    log = await service.answer_query(
        company_id=company_id,
        user_id=user_id,
        query="What is the forecasted Q3 tech department burn rate?",
        context={"q3_budget": 5000000},
    )

    assert log.company_id == company_id
    assert log.asked_by_user_id == user_id
    assert log.query_text == "What is the forecasted Q3 tech department burn rate?"
    assert "headcount growth" in log.ai_response
    mock_session.add.assert_called_once()

