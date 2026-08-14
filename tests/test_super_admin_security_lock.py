"""Comprehensive test suite for the Single Fixed Super Admin Security Lock.

Enforces:
1. Exactly ONE authorized Super Admin identity: superadmin@ofc360.com
2. Dual verification: email == superadmin@ofc360.com AND role == SUPER_ADMIN
3. Zero public Super Admin registrations / injection attempts
4. Zero HR Admin user creation/update escalation paths
5. Zero Employee / Manager / Profile escalation paths
6. JWT claim manipulation protection and database identity checks
7. Safe migration of legacy/duplicate super admin accounts
8. Database model level validation
"""

from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest
from pydantic import ValidationError
from fastapi import HTTPException

from app.core.rbac import require_super_admin, OFFICIAL_SUPER_ADMIN_EMAIL, ROLE_SUPER_ADMIN
from app.models.user import User, UserRole, UserAccountStatus
from app.schemas.auth import RegisterRequest
from app.schemas.hr_admin import HRAdminCreateUserRequest, HRAdminUpdateUserRequest
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.services.auth_service import AuthService
from app.services.hr_admin_service import HRAdminService
from app.services.employee_service import EmployeeService
from app.services.account_service import AccountService
from app.core.exceptions import AppException, ConflictException
from seed_super_admin import seed_super_admin


# ==============================================================================
# 1. Database Model Level Protection
# ==============================================================================

def test_model_prevents_non_superadmin_email_from_holding_superadmin_role():
    """Verify that User model rejects role=SUPER_ADMIN for non-superadmin emails."""
    with pytest.raises(ValueError) as exc_info:
        User(
            id=uuid.uuid4(),
            name="Imposter Admin",
            email="imposter@example.com",
            phone="9876543210",
            password_hash="fakehash",
            role=UserRole.SUPER_ADMIN,
        )
    assert "Security Lock Violation" in str(exc_info.value)
    assert "superadmin@ofc360.com" in str(exc_info.value)


def test_model_permits_official_superadmin_email_with_superadmin_role():
    """Verify that User model allows role=SUPER_ADMIN exclusively for superadmin@ofc360.com."""
    sa = User(
        id=uuid.uuid4(),
        name="Platform Super Admin",
        email="superadmin@ofc360.com",
        phone="9999900000",
        password_hash="fakehash",
        role=UserRole.SUPER_ADMIN,
    )
    assert sa.role == UserRole.SUPER_ADMIN
    assert sa.email == "superadmin@ofc360.com"
    assert sa.is_super_admin is True


def test_model_is_super_admin_property_requires_both_email_and_role():
    """Verify that is_super_admin returns False if either email or role does not match."""
    # Correct email, wrong role
    u1 = User(name="Test", email="superadmin@ofc360.com", phone="9999900000", password_hash="h", role=UserRole.HR_ADMIN)
    assert u1.is_super_admin is False

    # Normal user
    u2 = User(name="Emp", email="employee@company.com", phone="9999900001", password_hash="h", role=UserRole.EMPLOYEE)
    assert u2.is_super_admin is False


def test_model_prevents_changing_superadmin_email():
    """Verify that email cannot be changed away from superadmin@ofc360.com if role is SUPER_ADMIN."""
    sa = User(
        name="Platform Super Admin",
        email="superadmin@ofc360.com",
        phone="9999900000",
        password_hash="fakehash",
        role=UserRole.SUPER_ADMIN,
    )
    with pytest.raises(ValueError) as exc_info:
        sa.email = "new_email@ofc360.com"
    assert "Security Lock Violation" in str(exc_info.value)


# ==============================================================================
# 2. Public Registration Security Lock
# ==============================================================================

def test_register_schema_rejects_super_admin_role_injection():
    """Verify that public RegisterRequest rejects any payload specifying role=SUPER_ADMIN."""
    for injection_val in ["SUPER_ADMIN", "super_admin", "superadmin", "SUPERADMIN"]:
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                name="Attacker",
                email="attacker@test.com",
                phone="9876543210",
                password="SecurePassword@123",
                company_name="Evil Corp",
                role=injection_val,
            )
        assert "SUPER_ADMIN" in str(exc_info.value)


def test_register_schema_rejects_super_admin_email():
    """Verify that public RegisterRequest rejects attempts to register superadmin@ofc360.com."""
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            name="Super Admin Imposter",
            email="superadmin@ofc360.com",
            phone="9876543210",
            password="SecurePassword@123",
            company_name="My Company",
        )
    assert "Super Admin email cannot be registered" in str(exc_info.value)


@pytest.mark.asyncio
async def test_auth_service_register_rejects_super_admin_email():
    """Verify that AuthService.register_user rejects superadmin@ofc360.com registration."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    req = RegisterRequest(
        name="Test HR",
        email="test.hr@example.com",
        phone="9876543210",
        password="ValidPassword@123",
        company_name="Acme Corp",
    )
    # Force email to superadmin to test service-level guard
    req.__dict__["email"] = "superadmin@ofc360.com"

    with pytest.raises(AppException) as exc_info:
        await service.register_user(req)
    assert exc_info.value.status_code == 403
    assert "Super Admin" in exc_info.value.message


# ==============================================================================
# 3. HR Admin User Creation & Escalation Protection
# ==============================================================================

def test_hr_admin_create_schema_rejects_super_admin():
    """Verify that HR Admin user creation schema rejects role=SUPER_ADMIN."""
    with pytest.raises(ValidationError) as exc_info:
        HRAdminCreateUserRequest(
            first_name="Hacker",
            email="hacker@company.com",
            role="SUPER_ADMIN",
        )
    assert "Super Admin" in str(exc_info.value)


def test_hr_admin_create_schema_rejects_superadmin_email():
    """Verify that HR Admin user creation schema rejects superadmin@ofc360.com email."""
    with pytest.raises(ValidationError) as exc_info:
        HRAdminCreateUserRequest(
            first_name="Test",
            email="superadmin@ofc360.com",
            role="EMPLOYEE",
        )
    assert "Super Admin email" in str(exc_info.value)


def test_hr_admin_update_schema_rejects_super_admin():
    """Verify that HR Admin user update schema rejects role=SUPER_ADMIN."""
    with pytest.raises(ValidationError) as exc_info:
        HRAdminUpdateUserRequest(role="SUPER_ADMIN")
    assert "Super Admin" in str(exc_info.value)


@pytest.mark.asyncio
async def test_hr_admin_service_rejects_super_admin_creation():
    """Verify that HRAdminService.create_user blocks super_admin role."""
    mock_session = AsyncMock()
    mock_email = AsyncMock()
    service = HRAdminService(session=mock_session, email_service=mock_email)

    payload = MagicMock()
    payload.role = "SUPER_ADMIN"
    payload.email = "test@company.com"

    with pytest.raises(AppException) as exc_info:
        await service.create_user(admin_id=uuid.uuid4(), company_id=uuid.uuid4(), payload=payload)
    assert exc_info.value.status_code == 403


# ==============================================================================
# 4. Employee Management Escalation Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_employee_service_create_rejects_super_admin_role():
    """Verify that EmployeeService.create_employee rejects super_admin role."""
    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email = AsyncMock()
    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email,
    )

    payload = MagicMock(spec=EmployeeCreate)
    payload.personal_email = "emp@company.com"
    payload.company_email = None
    payload.role = "super_admin"

    with pytest.raises(AppException) as exc_info:
        await service.create_employee(admin_id=uuid.uuid4(), company_id=uuid.uuid4(), payload=payload)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_employee_service_create_rejects_superadmin_email():
    """Verify that EmployeeService.create_employee rejects personal_email=superadmin@ofc360.com."""
    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    mock_emp_repo = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email = AsyncMock()
    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_emp_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email,
    )

    payload = MagicMock(spec=EmployeeCreate)
    payload.personal_email = "superadmin@ofc360.com"
    payload.company_email = None
    payload.role = "employee"

    with pytest.raises(ConflictException) as exc_info:
        await service.create_employee(admin_id=uuid.uuid4(), company_id=uuid.uuid4(), payload=payload)
    assert "Super Admin email" in exc_info.value.message


# ==============================================================================
# 5. Account Service Email Change Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_account_service_change_email_locks_super_admin():
    """Verify that Super Admin cannot change email, and normal user cannot change to superadmin email."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    service = AccountService(session=mock_session, auth_repository=mock_repo, email_service=mock_email)

    # 1. Super Admin attempting to change email
    sa_user = User(
        id=uuid.uuid4(),
        name="Super Admin",
        email="superadmin@ofc360.com",
        phone="9999900000",
        password_hash="$2b$12$fakehash",
        role=UserRole.SUPER_ADMIN,
    )
    mock_repo.get_user_by_id.return_value = sa_user

    payload_sa = MagicMock()
    payload_sa.password = "ValidPass123"
    payload_sa.new_email = "newadmin@ofc360.com"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.account_service.verify_password", lambda p, h: True)
        with pytest.raises(AppException) as exc_info:
            await service.change_email(user_id=sa_user.id, payload=payload_sa)
        assert exc_info.value.status_code == 403
        assert "immutable" in exc_info.value.message

    # 2. Normal user attempting to claim superadmin email
    normal_user = User(
        id=uuid.uuid4(),
        name="Normal User",
        email="user@company.com",
        phone="9999900001",
        password_hash="$2b$12$fakehash",
        role=UserRole.EMPLOYEE,
    )
    mock_repo.get_user_by_id.return_value = normal_user
    payload_user = MagicMock()
    payload_user.password = "ValidPass123"
    payload_user.new_email = "superadmin@ofc360.com"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.account_service.verify_password", lambda p, h: True)
        with pytest.raises(AppException) as exc_info:
            await service.change_email(user_id=normal_user.id, payload=payload_user)
        assert exc_info.value.status_code == 403
        assert "Super Admin identity" in exc_info.value.message


# ==============================================================================
# 6. RBAC Dependency Verification
# ==============================================================================

@pytest.mark.asyncio
async def test_require_super_admin_permits_official_identity():
    """Verify that require_super_admin permits official superadmin claims."""
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "super_admin",
        "email": "superadmin@ofc360.com",
    }
    res = await require_super_admin(claims=claims, session=None)
    assert res == claims


@pytest.mark.asyncio
async def test_require_super_admin_rejects_imposter_claims():
    """Verify that require_super_admin rejects non-authorized email with super_admin role."""
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "super_admin",
        "email": "hacker@evil.com",
    }
    with pytest.raises(HTTPException) as exc_info:
        await require_super_admin(claims=claims, session=None)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_super_admin_db_identity_check():
    """Verify database-level check in require_super_admin."""
    mock_session = AsyncMock()
    user_id = uuid.uuid4()

    # User in DB matches official superadmin
    sa_user = User(
        id=user_id,
        name="Platform Super Admin",
        email="superadmin@ofc360.com",
        phone="9999900000",
        password_hash="h",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    mock_res = MagicMock()
    mock_res.scalars.return_value.first.return_value = sa_user
    mock_session.execute.return_value = mock_res

    claims = {"sub": str(user_id), "role": "super_admin", "email": "superadmin@ofc360.com"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.repositories.auth_repository.AuthRepository.get_user_by_id", AsyncMock(return_value=sa_user))
        res = await require_super_admin(claims=claims, session=mock_session)
        assert res == claims

    # DB user has wrong email or inactive
    sa_user.is_active = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.repositories.auth_repository.AuthRepository.get_user_by_id", AsyncMock(return_value=sa_user))
        with pytest.raises(HTTPException) as exc_info:
            await require_super_admin(claims=claims, session=mock_session)
        assert exc_info.value.status_code == 403


# ==============================================================================
# 7. Seed CLI Security Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_seed_cli_rejects_non_superadmin_email():
    """Verify seed_super_admin script refuses to seed any email other than superadmin@ofc360.com."""
    with pytest.raises(ValueError) as exc_info:
        await seed_super_admin(
            email="other@test.com",
            password="SuperAdmin@2026",
            name="Fake Admin",
            phone="9999999999",
        )
    assert "Security Lock Violation" in str(exc_info.value)


# ==============================================================================
# 8. Login Role Enforcement & Startup Migration
# ==============================================================================

@pytest.mark.asyncio
async def test_official_super_admin_login_returns_super_admin_role():
    """Verify official super admin login issues tokens with super_admin role."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_token_svc.generate_auth_tokens.return_value = ("access_jwt", "refresh_jwt", 1800)

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    sa_user = User(
        id=uuid.uuid4(),
        name="Platform Super Admin",
        email="superadmin@ofc360.com",
        phone="9999900000",
        password_hash="$2b$12$fakehash",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
    )
    mock_repo.get_user_by_identifier.return_value = sa_user

    payload = MagicMock()
    payload.identifier = "superadmin@ofc360.com"
    payload.password = "SuperAdmin@2026"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.auth_service.verify_password", lambda p, h: True)
        user, access, refresh, expires = await service.login(payload)

    assert user.role == UserRole.SUPER_ADMIN
    assert access == "access_jwt"
    # Ensure token service was called with email="superadmin@ofc360.com"
    call_kwargs = mock_token_svc.generate_auth_tokens.call_args.kwargs
    assert call_kwargs["role"] == "super_admin"
    assert call_kwargs["email"] == "superadmin@ofc360.com"


@pytest.mark.asyncio
async def test_login_downgrades_unauthorized_superadmin_role():
    """Verify login downgrades any non-official email having role=SUPER_ADMIN."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_token_svc.generate_auth_tokens.return_value = ("access_jwt", "refresh_jwt", 1800)

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    rogue_user = User(
        id=uuid.uuid4(),
        name="Rogue User",
        email="rogue@example.com",
        phone="9999900002",
        password_hash="$2b$12$fakehash",
        role=UserRole.EMPLOYEE,  # initialized as employee
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
    )
    # Bypass validator dynamically to simulate historical bad DB data
    rogue_user.__dict__["role"] = UserRole.SUPER_ADMIN
    mock_repo.get_user_by_identifier.return_value = rogue_user

    payload = MagicMock()
    payload.identifier = "rogue@example.com"
    payload.password = "AnyPass123"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.auth_service.verify_password", lambda p, h: True)
        user, access, refresh, expires = await service.login(payload)

    assert user.role == UserRole.EMPLOYEE
    call_kwargs = mock_token_svc.generate_auth_tokens.call_args.kwargs
    assert call_kwargs["role"] == "employee"


@pytest.mark.asyncio
async def test_ensure_superadmin_provisioned_safe_migration():
    """Verify startup ensures superadmin@ofc360.com and safely migrates duplicate superadmins."""
    from app.main import ensure_superadmin_provisioned

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # Legacy duplicate user that was super admin
    legacy_user = User(
        id=uuid.uuid4(),
        name="Legacy Admin",
        email="sharmavinit7348@gmail.com",
        phone="9351608590",
        password_hash="h",
        role=UserRole.EMPLOYEE,
    )
    legacy_user.__dict__["role"] = UserRole.SUPER_ADMIN

    # Query 1: non_sa_res -> returns legacy_user
    mock_non_sa_res = MagicMock()
    mock_non_sa_res.scalars.return_value.all.return_value = [legacy_user]

    # Query 2: sa_res -> returns None (superadmin doesn't exist yet)
    mock_sa_res = MagicMock()
    mock_sa_res.scalars.return_value.first.return_value = None

    mock_session.execute.side_effect = [mock_non_sa_res, mock_sa_res]

    with pytest.MonkeyPatch.context() as mp:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        mp.setattr("app.db.database.AsyncSessionLocal", lambda: mock_ctx)

        await ensure_superadmin_provisioned()

    # 1. Legacy user demoted to HR_ADMIN
    assert legacy_user.role == UserRole.HR_ADMIN

    # 2. Official super admin created
    added = [c.args[0] for c in mock_session.add.call_args_list]
    sa_added = [u for u in added if isinstance(u, User) and u.email == "superadmin@ofc360.com"]
    assert len(sa_added) == 1
    assert sa_added[0].role == UserRole.SUPER_ADMIN
    assert sa_added[0].is_active is True
    assert sa_added[0].is_verified is True

