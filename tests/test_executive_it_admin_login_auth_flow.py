"""End-to-End Authentication and Login Flow Tests for Executive/CXO and IT/System Admin."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.core.rbac import (
    ADMIN_MANAGER_ROLES,
    ADMIN_ROLES,
    EXECUTIVE_ROLES,
    IT_ADMIN_ROLES,
    ROLE_EXECUTIVE,
    ROLE_HR_ADMIN,
    ROLE_IT_ADMIN,
    ROLE_MANAGER,
    ROLE_SUPER_ADMIN,
    RoleEnum,
    UserRole,
    require_admin,
    require_admin_or_manager,
    require_executive,
    require_it_admin,
)
from app.core.security import hash_password
from app.utils.jwt import create_access_token
from app.db.database import get_db_session
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserAccountStatus
from app.repositories.auth_repository import AuthRepository
from app.services.auth_service import AuthService, get_auth_service
from app.services.email_service import EmailService


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_user(
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    email: str = "executive@example.com",
    role: UserRole = UserRole.EXECUTIVE,
    password_raw: str = "SecurePass@2026",
    is_active: bool = True,
    is_verified: bool = True,
    account_status: str = "ACTIVE",
) -> User:
    u = User(
        id=user_id or uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        name="Executive CXO User",
        email=email.lower().strip(),
        phone="9876543210",
        password_hash=hash_password(password_raw),
        role=role,
        is_active=is_active,
        is_verified=is_verified,
        account_status=account_status,
        onboarding_completed=True,
    )
    return u


def make_test_employee(
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    role: str = "executive",
    is_active: bool = True,
    status_val: str = "ACTIVE",
) -> Employee:
    return Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        company_id=company_id,
        employee_id=f"EMP-{uuid.uuid4().hex[:6].upper()}",
        first_name="Executive",
        last_name="Leader",
        personal_email="executive.leader@example.com",
        company_email="executive@example.com",
        phone="9876543210",
        department="Executive Leadership",
        designation="Chief Executive Officer",
        role=role,
        is_active=is_active,
        status=status_val,
        is_deleted=False,
    )


# ==============================================================================
# 1. Executive / CXO Login & Dashboard Authorization Flow
# ==============================================================================

@pytest.mark.asyncio
async def test_executive_login_success_and_token_response():
    """Verify Executive/CXO login issues valid tokens, correct role, and consistent auth response."""
    app = create_app()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    raw_pass = "ExecutivePass@2026"
    exec_user = make_test_user(
        user_id=user_id,
        company_id=company_id,
        email="cxo@ofc360.com",
        role=UserRole.EXECUTIVE,
        password_raw=raw_pass,
    )

    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_auth_repo.get_user_by_identifier.return_value = exec_user
    mock_auth_repo.get_user_by_id.return_value = exec_user
    mock_auth_repo.create_refresh_token.return_value = MagicMock()
    mock_auth_repo.update_login_audit.return_value = None

    mock_session = AsyncMock()
    # Mock no conflicting deactivated employee/manager profile
    mock_session.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))

    auth_service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=AsyncMock(spec=EmailService),
    )
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_db_session] = lambda: mock_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "cxo@ofc360.com", "password": raw_pass},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["access_token"] is not None
        assert data["data"]["refresh_token"] is not None
        assert data["data"]["user"]["role"] == "executive"
        assert data["data"]["user"]["email"] == "cxo@ofc360.com"


@pytest.mark.asyncio
async def test_executive_can_access_executive_endpoints():
    """Verify Executive/CXO bearer token successfully passes require_executive and require_admin_or_manager dependencies."""
    app = create_app()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    exec_token = create_access_token(user_id=user_id, role="executive", company_id=company_id, email="cxo@ofc360.com")

    # 1. Dependency checks directly
    claims = {"sub": str(user_id), "role": "executive", "company_id": str(company_id), "email": "cxo@ofc360.com"}
    assert require_executive(claims) == claims
    assert require_admin_or_manager(claims) == claims

    # 2. C-Suite alias token checks
    for c_role in ["ceo", "cto", "cfo", "coo", "cio", "ciso", "cxo"]:
        c_claims = {"sub": str(user_id), "role": c_role, "company_id": str(company_id)}
        assert require_executive(c_claims) == c_claims
        assert require_admin_or_manager(c_claims) == c_claims


@pytest.mark.asyncio
async def test_executive_sidebar_permissions():
    """Verify Executive/CXO receives full management and analytics sidebar menu visibility."""
    from app.api.sidebar import _get_permissions_for_role

    for role_name in ["executive", "EXECUTIVE", "ceo", "CEO", "cto", "cfo", "coo", "cxo"]:
        perms_data = _get_permissions_for_role(role_name)
        assert perms_data["modules"]["dashboard"] is True
        assert perms_data["modules"]["employees"] is True
        assert perms_data["modules"]["analytics"] is True
        assert perms_data["modules"]["departments"] is True


# ==============================================================================
# 2. IT / System Admin Login & Protected API Flow
# ==============================================================================

@pytest.mark.asyncio
async def test_it_admin_login_success_and_token_response():
    """Verify IT/System Admin login issues valid tokens and correct IT Admin role."""
    app = create_app()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    raw_pass = "ITAdminPass@2026"
    it_user = make_test_user(
        user_id=user_id,
        company_id=company_id,
        email="itadmin@ofc360.com",
        role=UserRole.IT_ADMIN,
        password_raw=raw_pass,
    )

    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_auth_repo.get_user_by_identifier.return_value = it_user
    mock_auth_repo.get_user_by_id.return_value = it_user
    mock_auth_repo.create_refresh_token.return_value = MagicMock()
    mock_auth_repo.update_login_audit.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))

    auth_service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=AsyncMock(spec=EmailService),
    )
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_db_session] = lambda: mock_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "itadmin@ofc360.com", "password": raw_pass},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["access_token"] is not None
        assert data["data"]["user"]["role"] == "it_admin"
        assert data["data"]["user"]["email"] == "itadmin@ofc360.com"


@pytest.mark.asyncio
async def test_it_admin_can_access_admin_and_it_endpoints():
    """Verify IT/System Admin token passes require_it_admin and require_admin dependencies."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # 1. Standard IT Admin role
    it_claims = {"sub": str(user_id), "role": "it_admin", "company_id": str(company_id), "email": "itadmin@ofc360.com"}
    assert require_it_admin(it_claims) == it_claims
    assert require_admin(it_claims) == it_claims
    assert require_admin_or_manager(it_claims) == it_claims

    # 2. System Admin alias claims
    for it_alias in ["system_admin", "itadmin", "it_system_admin", "tech_admin", "sysadmin"]:
        alias_claims = {"sub": str(user_id), "role": it_alias, "company_id": str(company_id)}
        assert require_it_admin(alias_claims) == alias_claims
        assert require_admin(alias_claims) == alias_claims
        assert require_admin_or_manager(alias_claims) == alias_claims


@pytest.mark.asyncio
async def test_it_admin_sidebar_permissions():
    """Verify IT/System Admin receives administrative sidebar permissions."""
    from app.api.sidebar import _get_permissions_for_role

    for role_name in ["it_admin", "IT_ADMIN", "system_admin", "SYSTEM_ADMIN", "itadmin", "tech_admin"]:
        perms_data = _get_permissions_for_role(role_name)
        assert perms_data["modules"]["dashboard"] is True
        assert perms_data["modules"]["settings"] is True
        assert perms_data["modules"]["employees"] is True


# ==============================================================================
# 3. Negative & Security Edge Cases
# ==============================================================================

@pytest.mark.asyncio
async def test_login_invalid_password_returns_401():
    """Verify invalid password on login returns 401 Unauthorized."""
    app = create_app()
    exec_user = make_test_user(password_raw="CorrectPassword@123")

    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_auth_repo.get_user_by_identifier.return_value = exec_user
    mock_session = AsyncMock()

    auth_service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=AsyncMock(spec=EmailService),
    )
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_db_session] = lambda: mock_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/auth/login",
            json={"identifier": exec_user.email, "password": "WrongPassword@999"},
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_it_admin_cannot_access_hr_admin_only_endpoints():
    """Verify IT Admin cannot bypass HR Admin specific endpoints (returns 403 Forbidden)."""
    from fastapi import HTTPException
    from app.core.rbac import require_hr_admin

    claims = {"sub": str(uuid.uuid4()), "role": "it_admin"}
    with pytest.raises(HTTPException) as exc_info:
        require_hr_admin(claims)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "HR Admin access required" in exc_info.value.detail
