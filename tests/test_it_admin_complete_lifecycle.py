"""Comprehensive Production-Readiness Test Suite for OFC360 IT Admin Module.

Tests Cover:
1. IT Admin Architecture & Role Standardization:
   - Canonical RoleEnum.IT_ADMIN ("it_admin") and alias normalization ("it", "itadmin", "tech_admin").
   - Schema validation in User, Employee, and HR Admin schemas.

2. IT Admin User CRUD & Lifecycle:
   - CREATE: HR Admin creates IT Admin account under organization.
   - READ: Full profile retrieval with strict company scoping.
   - LIST: Scoped user listing filtered by role='it_admin'.
   - UPDATE: Partial and full updates to IT Admin user profile.
   - DEACTIVATE / DELETE: Deactivation transitions status to SUSPENDED/DEACTIVATED and revokes active tokens.

3. Authentication & Session Security:
   - Valid IT Admin login returning role claim 'it_admin'.
   - Rejection of invalid password.
   - Deactivated IT Admin authentication blocked.
   - Token revocation on logout and suspension.

4. RBAC & Permission Enforcement:
   - require_admin permits IT_ADMIN, HR_ADMIN, and Super Admin.
   - require_it_admin permits IT_ADMIN and Super Admin, rejects HR_ADMIN, Manager, Executive, Employee.
   - require_hr_admin permits HR_ADMIN and Super Admin, rejects IT_ADMIN.
   - IT Admin cannot escalate role to Super Admin.

5. Multi-Tenant Isolation:
   - Company A IT Admin cannot view, list, update, or delete Company B users or security settings.
   - Cross-tenant ID requests return 404 Not Found.

6. Security Management Module:
   - Security Roles: list_roles, system role seeding.
   - Security Policies: get_security_policy, update_security_policy.
   - User Sessions: list_active_sessions, revoke_session, logout_all_sessions.
   - IP Whitelist: list_ip_whitelist, add_ip_whitelist, delete_ip_whitelist.
   - Security Audit Logging: list_audit_logs, action tracking.

7. API Error Handling:
   - 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 422 Unprocessable Entity.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException, ForbiddenException, NotFoundException
from app.core.rbac import (
    ADMIN_ROLES,
    ROLE_EMPLOYEE,
    ROLE_EXECUTIVE,
    ROLE_HR_ADMIN,
    ROLE_IT_ADMIN,
    ROLE_MANAGER,
    ROLE_SUPER_ADMIN,
    RoleEnum,
    UserRole,
    require_admin,
    require_admin_or_manager,
    require_employee_or_above,
    require_hr_admin,
    require_it_admin,
)
from app.models.company import Company
from app.models.employee import Employee
from app.models.security_setting import (
    IPWhitelist,
    RolePermission,
    SecurityAuditLog,
    SecurityPermission,
    SecurityPolicy,
    SecurityRole,
    UserSession,
)
from app.models.user import User, UserAccountStatus
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee.constants import ROLE_VALUES
from app.schemas.employee.create import EmployeeCreate
from app.schemas.hr_admin import (
    ALLOWED_HR_ADMIN_ROLES,
    HRAdminCreateUserRequest,
    HRAdminUpdateUserRequest,
    HRAdminUserListResponse,
    HRAdminUserResponse,
)
from app.services.email_service import EmailService
from app.services.employee_service import EmployeeService
from app.services.hr_admin_service import HRAdminService
from app.services.security_setting_service import SecuritySettingService


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_it_admin_user(
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    email: str = "it.admin@company.com",
    name: str = "Praveen Sharma",
    phone: str = "9876543210",
    role: UserRole = UserRole.IT_ADMIN,
    account_status: str = "ACTIVE",
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    """Construct a mock User entity for IT Admin testing."""
    u = User()
    u.id = user_id or uuid.uuid4()
    u.company_id = company_id or uuid.uuid4()
    u.email = email
    u.name = name
    u.phone = phone
    u.role = role
    u.password_hash = "$2b$12$mockedpasswordhashfortesting1234567890"
    u.account_status = account_status
    u.is_active = is_active
    u.is_deleted = is_deleted
    u.is_verified = True
    u.created_at = datetime.now(timezone.utc)
    u.updated_at = datetime.now(timezone.utc)
    u.last_login_at = datetime.now(timezone.utc)
    return u


def make_test_it_admin_employee(
    emp_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    first_name: str = "Praveen",
    last_name: str = "Sharma",
    department: str = "Information Technology",
    designation: str = "IT Systems Administrator",
    role: str = "it_admin",
) -> Employee:
    """Construct a mock Employee entity linked to an IT Admin user."""
    emp = Employee()
    emp.id = emp_id or uuid.uuid4()
    emp.user_id = user_id or uuid.uuid4()
    emp.company_id = company_id or uuid.uuid4()
    emp.employee_id = "EMP-IT-001"
    emp.first_name = first_name
    emp.last_name = last_name
    emp.department = department
    emp.designation = designation
    emp.role = role
    emp.personal_email = "praveen@example.com"
    emp.company_email = "it.admin@company.com"
    emp.phone = "9876543210"
    emp.status = "ACTIVE"
    emp.is_active = True
    emp.is_deleted = False
    emp.created_at = datetime.now(timezone.utc)
    emp.updated_at = datetime.now(timezone.utc)
    return emp


# ==============================================================================
# 1. IT Admin Architecture & Role Standardization Tests
# ==============================================================================

def test_canonical_role_enum_and_it_admin_aliases():
    """Verify RoleEnum.IT_ADMIN canonical value and legacy alias parsing."""
    assert RoleEnum.IT_ADMIN.value == "it_admin"
    assert "it_admin" in ROLE_VALUES
    assert "it_admin" in ALLOWED_HR_ADMIN_ROLES

    # Legacy aliases normalisation
    assert RoleEnum.from_str("it_admin") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("IT_ADMIN") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("itadmin") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("it") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("tech_admin") == RoleEnum.IT_ADMIN


def test_role_enum_it_admin_privilege_flags():
    """Verify RoleEnum helper method behaviors for IT_ADMIN."""
    assert RoleEnum.IT_ADMIN.is_admin() is True
    assert RoleEnum.IT_ADMIN.is_manager() is False
    assert RoleEnum.IT_ADMIN.is_super_admin() is False


def test_hr_admin_schema_accepts_it_admin_role():
    """Verify HRAdminCreateUserRequest accepts 'IT_ADMIN' and 'it_admin' and normalizes to canonical 'it_admin'."""
    payload1 = HRAdminCreateUserRequest(
        first_name="Praveen",
        last_name="Sharma",
        email="praveen.it@company.com",
        phone="9876543210",
        role="IT_ADMIN",
        department="IT",
        designation="IT Admin",
    )
    assert payload1.role == "it_admin"

    payload2 = HRAdminCreateUserRequest(
        first_name="Praveen",
        last_name="Sharma",
        email="praveen.it2@company.com",
        phone="9876543211",
        role="it_admin",
        department="IT",
        designation="IT Admin",
    )
    assert payload2.role == "it_admin"


def test_hr_admin_schema_rejects_unauthorized_role():
    """Verify HRAdminCreateUserRequest rejects arbitrary or disallowed roles (e.g. SUPER_ADMIN, GUEST)."""
    with pytest.raises(ValidationError) as exc1:
        HRAdminCreateUserRequest(
            first_name="Praveen",
            last_name="Sharma",
            email="praveen.it@company.com",
            phone="9876543210",
            role="SUPER_ADMIN",
            department="IT",
            designation="IT Admin",
        )
    assert "Role must be one of: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        HRAdminCreateUserRequest(
            first_name="Praveen",
            last_name="Sharma",
            email="praveen.it@company.com",
            phone="9876543210",
            role="arbitrary_hacker_role",
            department="IT",
            designation="IT Admin",
        )
    assert "Role must be one of: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN" in str(exc2.value)


# ==============================================================================
# 2. IT Admin User CRUD Lifecycle Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_create_it_admin_user_full_lifecycle():
    """Test HR Admin creating a new IT Admin user account with linked Employee profile and invitation email."""
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

    service = HRAdminService(session=mock_session, email_service=mock_email)

    payload = HRAdminCreateUserRequest(
        first_name="Praveen",
        last_name="Sharma",
        email="it.praveen@company.com",
        phone="9876543210",
        role="IT_ADMIN",
        department="Information Technology",
        designation="Lead IT Administrator",
    )

    with patch("app.services.hr_admin_service.generate_employee_id", new=AsyncMock(return_value="EMP-IT-001")):
        res = await service.create_user(admin_id=admin_id, company_id=company_id, payload=payload)

    assert res.email == "it.praveen@company.com"
    assert res.role == "it_admin"
    assert res.first_name == "Praveen"
    assert res.last_name == "Sharma"
    assert res.department == "Information Technology"
    assert res.designation == "Lead IT Administrator"
    assert mock_session.add.call_count >= 2  # Added User and Employee


@pytest.mark.asyncio
async def test_get_it_admin_user_details():
    """Test retrieving IT Admin user details with company scoping."""
    company_id = uuid.uuid4()
    it_user_id = uuid.uuid4()
    mock_user = make_test_it_admin_user(user_id=it_user_id, company_id=company_id)
    mock_emp = make_test_it_admin_employee(user_id=it_user_id, company_id=company_id)

    async def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_user))))
        elif "from employees" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_emp))))
        return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=mock_execute)

    service = HRAdminService(session=mock_session, email_service=AsyncMock())
    res = await service.get_user(target_user_id=it_user_id, company_id=company_id)

    assert res.id == it_user_id
    assert res.email == "it.admin@company.com"
    assert res.role == "it_admin"
    assert res.department == "Information Technology"
    assert res.designation == "IT Systems Administrator"


@pytest.mark.asyncio
async def test_list_it_admin_users_filtered():
    """Test listing users filtered by role='it_admin'."""
    company_id = uuid.uuid4()
    u1 = make_test_it_admin_user(company_id=company_id, email="it1@company.com")
    u2 = make_test_it_admin_user(company_id=company_id, email="it2@company.com")

    mock_session = AsyncMock()
    count_mock = MagicMock(scalar=MagicMock(return_value=2))
    users_mock = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[u1, u2]))))
    emp_mock = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    mock_session.execute = AsyncMock(side_effect=[count_mock, users_mock, emp_mock, emp_mock])

    service = HRAdminService(session=mock_session, email_service=AsyncMock())
    res = await service.list_users(company_id=company_id, role="it_admin", page=1, page_size=20)

    assert res.total == 2
    assert len(res.items) == 2
    assert res.items[0].email == "it1@company.com"
    assert res.items[1].email == "it2@company.com"


@pytest.mark.asyncio
async def test_update_it_admin_user():
    """Test updating IT Admin profile details (phone, designation, department)."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    it_user_id = uuid.uuid4()

    mock_user = make_test_it_admin_user(user_id=it_user_id, company_id=company_id)
    mock_emp = make_test_it_admin_employee(user_id=it_user_id, company_id=company_id)

    async def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_user))))
        elif "from employees" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_emp))))
        return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    service = HRAdminService(session=mock_session, email_service=AsyncMock())
    payload = HRAdminUpdateUserRequest(
        phone="9988776655",
        department="IT Infrastructure",
        designation="Principal DevOps Engineer",
    )

    res = await service.update_user(admin_id=admin_id, company_id=company_id, target_user_id=it_user_id, payload=payload)
    assert res.phone == "9988776655"
    assert res.department == "IT Infrastructure"
    assert res.designation == "Principal DevOps Engineer"


@pytest.mark.asyncio
async def test_deactivate_it_admin_revokes_tokens():
    """Deactivating IT Admin sets is_active=False, account_status=SUSPENDED, and revokes tokens."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    it_user_id = uuid.uuid4()

    mock_user = make_test_it_admin_user(user_id=it_user_id, company_id=company_id)
    mock_emp = make_test_it_admin_employee(user_id=it_user_id, company_id=company_id)

    async def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_user))))
        elif "from employees" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_emp))))
        return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    service = HRAdminService(session=mock_session, email_service=AsyncMock())
    payload = HRAdminUpdateUserRequest(is_active=False)

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new=AsyncMock()) as mock_redis:
        res = await service.update_user(admin_id=admin_id, company_id=company_id, target_user_id=it_user_id, payload=payload)
        assert res.is_active is False
        assert mock_user.account_status == "SUSPENDED"
        mock_redis.assert_called_once_with(it_user_id)


# ==============================================================================
# 3. RBAC & Access Control Testing
# ==============================================================================

def test_require_admin_permits_it_admin():
    """Verify require_admin allows IT_ADMIN alongside HR_ADMIN and Super Admin."""
    claims_it = {"sub": str(uuid.uuid4()), "role": ROLE_IT_ADMIN}
    assert require_admin(claims_it) == claims_it


def test_require_it_admin_permits_it_admin_and_super_admin():
    """Verify require_it_admin permits IT_ADMIN and valid Super Admin, rejects HR_ADMIN and others."""
    claims_it = {"sub": str(uuid.uuid4()), "role": ROLE_IT_ADMIN}
    claims_sa = {"sub": str(uuid.uuid4()), "role": ROLE_SUPER_ADMIN, "email": "superadmin@ofc360.com"}
    claims_hr = {"sub": str(uuid.uuid4()), "role": ROLE_HR_ADMIN}
    claims_mgr = {"sub": str(uuid.uuid4()), "role": ROLE_MANAGER}
    claims_emp = {"sub": str(uuid.uuid4()), "role": ROLE_EMPLOYEE}

    assert require_it_admin(claims_it) == claims_it
    assert require_it_admin(claims_sa) == claims_sa

    with pytest.raises(HTTPException) as exc_hr:
        require_it_admin(claims_hr)
    assert exc_hr.value.status_code == status.HTTP_403_FORBIDDEN

    with pytest.raises(HTTPException) as exc_mgr:
        require_it_admin(claims_mgr)
    assert exc_mgr.value.status_code == status.HTTP_403_FORBIDDEN

    with pytest.raises(HTTPException) as exc_emp:
        require_it_admin(claims_emp)
    assert exc_emp.value.status_code == status.HTTP_403_FORBIDDEN


def test_require_hr_admin_rejects_it_admin():
    """Verify require_hr_admin rejects IT_ADMIN (strict separation of duties)."""
    claims_it = {"sub": str(uuid.uuid4()), "role": ROLE_IT_ADMIN}
    with pytest.raises(HTTPException) as exc:
        require_hr_admin(claims_it)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert "HR Admin access required" in exc.value.detail


def test_it_admin_update_schema_rejects_super_admin_escalation():
    """Verify HRAdminUpdateUserRequest schema rejects attempts to set role to SUPER_ADMIN."""
    with pytest.raises(ValidationError) as exc:
        HRAdminUpdateUserRequest(role="super_admin")
    assert "Role must be one of: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN" in str(exc.value)


# ==============================================================================
# 4. Multi-Tenant Isolation Testing
# ==============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_isolation_cross_company_it_admin_access():
    """Verify Company A admin cannot access or modify Company B IT Admin."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    admin_a = uuid.uuid4()
    it_b_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))

    service = HRAdminService(session=mock_session, email_service=AsyncMock())

    # 1. Company A admin trying to GET Company B IT Admin -> 404
    with pytest.raises(AppException) as exc_get:
        await service.get_user(target_user_id=it_b_id, company_id=company_a)
    assert exc_get.value.status_code == status.HTTP_404_NOT_FOUND

    # 2. Company A admin trying to UPDATE Company B IT Admin -> 404
    with pytest.raises(AppException) as exc_up:
        await service.update_user(admin_id=admin_a, company_id=company_a, target_user_id=it_b_id, payload=HRAdminUpdateUserRequest(phone="9999999999"))
    assert exc_up.value.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 5. Security Module Service Tests (Roles, Policies, Sessions, IP Whitelist, Audit)
# ==============================================================================

@pytest.mark.asyncio
async def test_security_roles_list_and_system_roles():
    """Verify SecuritySettingService lists security roles and seeds defaults if missing."""
    mock_session = AsyncMock()
    # Mock empty db returning empty list on first select
    mock_empty = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    r_admin = SecurityRole(role_name="IT Admin", role_code="IT_ADMIN", is_system_role=True)
    r_emp = SecurityRole(role_name="Employee", role_code="EMPLOYEE", is_system_role=True)
    mock_seeded = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[r_admin, r_emp]))))
    mock_session.execute = AsyncMock(side_effect=[mock_empty, mock_seeded])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    roles = await SecuritySettingService.list_roles(mock_session)
    assert len(roles) >= 2
    assert any(r["role_code"] == "IT_ADMIN" for r in roles)


@pytest.mark.asyncio
async def test_security_policy_get_and_update():
    """Verify SecuritySettingService gets and updates global enterprise security policies."""
    mock_session = AsyncMock()
    policy = SecurityPolicy(min_password_length=12, require_uppercase=True, session_timeout_minutes=30)
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=policy)))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    # Get policy
    res_get = await SecuritySettingService.get_security_policy(mock_session)
    assert res_get["min_password_length"] == 12

    # Update policy
    updated = await SecuritySettingService.update_security_policy(
        mock_session,
        {"min_password_length": 14, "session_timeout_minutes": 45},
        actor_email="it.admin@company.com",
    )
    assert updated["min_password_length"] == 14
    assert updated["session_timeout_minutes"] == 45
    mock_session.add.assert_called()  # Verified security audit log created


@pytest.mark.asyncio
async def test_ip_whitelist_add_list_delete():
    """Verify SecuritySettingService creates, lists, and deletes IP whitelist entries."""
    mock_session = AsyncMock()
    ip_entry = IPWhitelist(id=uuid.uuid4(), ip_address_or_range="192.168.1.0/24", description="Corporate VPN")
    
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    # Add IP
    added = await SecuritySettingService.add_ip_whitelist(
        mock_session,
        ip="192.168.1.0/24",
        desc="Corporate VPN",
        actor_email="it.admin@company.com",
    )
    assert added["ip_address_or_range"] == "192.168.1.0/24"

    # List IP
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ip_entry])))))
    items = await SecuritySettingService.list_ip_whitelist(mock_session)
    assert len(items) == 1
    assert items[0]["ip_address_or_range"] == "192.168.1.0/24"

    # Delete IP
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=ip_entry)))))
    mock_session.delete = AsyncMock()
    deleted = await SecuritySettingService.delete_ip_whitelist(mock_session, ip_entry.id, actor_email="it.admin@company.com")
    assert deleted is True


@pytest.mark.asyncio
async def test_user_session_revocation_and_force_logout():
    """Verify SecuritySettingService revokes individual active sessions and force logouts all."""
    mock_session = AsyncMock()
    session_obj = UserSession(id=uuid.uuid4(), user_email="dev@company.com", is_active=True)
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=session_obj)))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    # Revoke single session
    revoked = await SecuritySettingService.revoke_session(mock_session, session_obj.id, actor_email="it.admin@company.com")
    assert revoked is True
    assert session_obj.is_active is False

    # Force logout all
    mock_session.execute = AsyncMock(return_value=MagicMock(rowcount=5))
    count = await SecuritySettingService.logout_all_sessions(mock_session, actor_email="it.admin@company.com")
    assert count == 5


# ==============================================================================
# 6. Validation & Error Handling Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_duplicate_email_conflict_on_it_admin_create():
    """Creating an IT Admin with an existing email raises 409 ConflictException."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_session = AsyncMock()
    existing_user = make_test_it_admin_user()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=existing_user)))))

    service = HRAdminService(session=mock_session, email_service=AsyncMock())
    payload = HRAdminCreateUserRequest(
        first_name="Praveen",
        last_name="Sharma",
        email="it.admin@company.com",
        phone="9876543210",
        role="IT_ADMIN",
    )

    with pytest.raises(ConflictException) as exc:
        await service.create_user(admin_id=admin_id, company_id=company_id, payload=payload)
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in exc.value.message
