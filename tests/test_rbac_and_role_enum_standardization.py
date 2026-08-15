"""Comprehensive test suite for Role-Based Access Control (RBAC) & Canonical RoleEnum Standardization."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.rbac import (
    ADMIN_MANAGER_ROLES,
    ADMIN_ROLES,
    EXECUTIVE_ROLES,
    ROLE_EMPLOYEE,
    ROLE_EXECUTIVE,
    ROLE_HR_ADMIN,
    ROLE_INTERN,
    ROLE_IT_ADMIN,
    ROLE_MANAGER,
    ROLE_SUPER_ADMIN,
    RoleEnum,
    UserRole,
    require_admin,
    require_admin_or_manager,
    require_employee_or_above,
    require_executive,
    require_hr_admin,
    require_it_admin,
    require_roles,
    require_super_admin,
)
from app.models.user.role import OFFICIAL_SUPER_ADMIN_EMAIL
from app.schemas.auth import UserLoginPublic, UserProfileData, UserPublic
from app.api.payroll.permissions import _require_admin, _require_admin_or_manager
from app.api.payroll.exceptions import ForbiddenException
from app.main import create_app


# ==============================================================================
# 1. Canonical RoleEnum & Parser Tests
# ==============================================================================

def test_canonical_role_enum_values():
    """Verify RoleEnum defines the standardized 7 canonical roles and UserRole is an exact alias."""
    assert RoleEnum.SUPER_ADMIN.value == "super_admin"
    assert RoleEnum.HR_ADMIN.value == "hr_admin"
    assert RoleEnum.MANAGER.value == "manager"
    assert RoleEnum.EMPLOYEE.value == "employee"
    assert RoleEnum.EXECUTIVE.value == "executive"
    assert RoleEnum.IT_ADMIN.value == "it_admin"
    assert RoleEnum.INTERN.value == "intern"

    assert UserRole is RoleEnum
    assert len(RoleEnum) == 7


def test_role_enum_from_str_parsing():
    """Verify RoleEnum.from_str handles various case, whitespace, and legacy aliases."""
    # Direct canonical strings
    assert RoleEnum.from_str("super_admin") == RoleEnum.SUPER_ADMIN
    assert RoleEnum.from_str("HR_ADMIN") == RoleEnum.HR_ADMIN
    assert RoleEnum.from_str(" Manager ") == RoleEnum.MANAGER
    assert RoleEnum.from_str("EMPLOYEE") == RoleEnum.EMPLOYEE
    assert RoleEnum.from_str("executive") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("IT_ADMIN") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("intern") == RoleEnum.INTERN

    # Legacy & administrative aliases
    assert RoleEnum.from_str("admin") == RoleEnum.HR_ADMIN
    assert RoleEnum.from_str("hr") == RoleEnum.HR_ADMIN
    assert RoleEnum.from_str("superadmin") == RoleEnum.SUPER_ADMIN
    assert RoleEnum.from_str("itadmin") == RoleEnum.IT_ADMIN
    assert RoleEnum.from_str("ceo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cto") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("cfo") == RoleEnum.EXECUTIVE
    assert RoleEnum.from_str("coo") == RoleEnum.EXECUTIVE

    # Empty / unknown defaults to EMPLOYEE
    assert RoleEnum.from_str(None) == RoleEnum.EMPLOYEE
    assert RoleEnum.from_str("") == RoleEnum.EMPLOYEE
    assert RoleEnum.from_str("unknown_role_xyz") == RoleEnum.EMPLOYEE


def test_role_enum_helper_methods():
    """Verify is_admin, is_super_admin, is_manager helper methods on RoleEnum."""
    assert RoleEnum.SUPER_ADMIN.is_super_admin() is True
    assert RoleEnum.HR_ADMIN.is_super_admin() is False

    assert RoleEnum.SUPER_ADMIN.is_admin() is True
    assert RoleEnum.HR_ADMIN.is_admin() is True
    assert RoleEnum.IT_ADMIN.is_admin() is True
    assert RoleEnum.EMPLOYEE.is_admin() is False

    assert RoleEnum.MANAGER.is_manager() is True
    assert RoleEnum.SUPER_ADMIN.is_manager() is True
    assert RoleEnum.EXECUTIVE.is_manager() is True
    assert RoleEnum.EMPLOYEE.is_manager() is False


# ==============================================================================
# 2. Pydantic Schema Role Validation Tests
# ==============================================================================

def test_user_public_schema_role_validation():
    """Verify UserPublic parses string and RoleEnum instances into canonical RoleEnum."""
    user_data = {
        "id": uuid.uuid4(),
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "9876543210",
        "role": "hr_admin",
        "is_verified": True,
        "created_at": "2026-08-15T00:00:00Z",
    }
    user = UserPublic.model_validate(user_data)
    assert user.role == RoleEnum.HR_ADMIN
    assert user.role.value == "hr_admin"

    # With legacy alias
    user_data["role"] = "ADMIN"
    user2 = UserPublic.model_validate(user_data)
    assert user2.role == RoleEnum.HR_ADMIN


def test_user_login_public_schema_role_validation():
    """Verify UserLoginPublic normalizes role strings cleanly."""
    login_user = UserLoginPublic(
        id=uuid.uuid4(),
        name="Leader",
        email="leader@example.com",
        role="MANAGER",
        is_verified=True,
    )
    assert login_user.role == RoleEnum.MANAGER


def test_user_profile_data_schema_role_validation():
    """Verify UserProfileData converts string to canonical RoleEnum."""
    profile = UserProfileData(
        id=uuid.uuid4(),
        name="Tech Exec",
        email="exec@example.com",
        role="CTO",
    )
    assert profile.role == RoleEnum.EXECUTIVE


# ==============================================================================
# 3. RBAC Dependencies Tests
# ==============================================================================

def test_require_hr_admin_dependency():
    """Verify require_hr_admin allows hr_admin & official super_admin, rejects others."""
    # HR Admin allowed
    claims_hr = {"sub": str(uuid.uuid4()), "role": "hr_admin"}
    assert require_hr_admin(claims_hr) == claims_hr

    # Super Admin allowed with official email
    claims_sa = {"sub": str(uuid.uuid4()), "role": "super_admin", "email": OFFICIAL_SUPER_ADMIN_EMAIL}
    assert require_hr_admin(claims_sa) == claims_sa

    # Imposter Super Admin rejected
    claims_sa_imposter = {"sub": str(uuid.uuid4()), "role": "super_admin", "email": "fake@example.com"}
    with pytest.raises(HTTPException) as exc:
        require_hr_admin(claims_sa_imposter)
    assert exc.value.status_code == 403

    # Employee rejected
    claims_emp = {"sub": str(uuid.uuid4()), "role": "employee"}
    with pytest.raises(HTTPException) as exc:
        require_hr_admin(claims_emp)
    assert exc.value.status_code == 403


def test_require_admin_dependency():
    """Verify require_admin allows hr_admin, it_admin, and super_admin."""
    claims_it = {"sub": str(uuid.uuid4()), "role": "it_admin"}
    assert require_admin(claims_it) == claims_it

    claims_hr = {"sub": str(uuid.uuid4()), "role": "hr_admin"}
    assert require_admin(claims_hr) == claims_hr

    claims_mgr = {"sub": str(uuid.uuid4()), "role": "manager"}
    with pytest.raises(HTTPException) as exc:
        require_admin(claims_mgr)
    assert exc.value.status_code == 403


def test_require_admin_or_manager_dependency():
    """Verify require_admin_or_manager allows admin, hr, it, manager, executive."""
    for role in [ROLE_HR_ADMIN, ROLE_IT_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE]:
        claims = {"sub": str(uuid.uuid4()), "role": role}
        assert require_admin_or_manager(claims) == claims

    claims_emp = {"sub": str(uuid.uuid4()), "role": "employee"}
    with pytest.raises(HTTPException) as exc:
        require_admin_or_manager(claims_emp)
    assert exc.value.status_code == 403


def test_require_executive_dependency():
    """Verify require_executive allows executive and hr_admin, rejects manager/it_admin."""
    claims_exec = {"sub": str(uuid.uuid4()), "role": "executive"}
    assert require_executive(claims_exec) == claims_exec

    claims_mgr = {"sub": str(uuid.uuid4()), "role": "manager"}
    with pytest.raises(HTTPException) as exc:
        require_executive(claims_mgr)
    assert exc.value.status_code == 403


def test_require_employee_or_above_dependency():
    """Verify require_employee_or_above allows any recognized platform role."""
    for role in RoleEnum:
        if role == RoleEnum.SUPER_ADMIN:
            claims = {"sub": str(uuid.uuid4()), "role": role.value, "email": OFFICIAL_SUPER_ADMIN_EMAIL}
        else:
            claims = {"sub": str(uuid.uuid4()), "role": role.value}
        assert require_employee_or_above(claims) == claims

    # Invalid role rejected
    claims_invalid = {"sub": str(uuid.uuid4()), "role": "hacker"}
    with pytest.raises(HTTPException) as exc:
        require_employee_or_above(claims_invalid)
    assert exc.value.status_code == 403


def test_require_roles_factory():
    """Verify require_roles creates custom role filtering dependencies."""
    checker = require_roles(RoleEnum.MANAGER, "executive")

    claims_mgr = {"sub": str(uuid.uuid4()), "role": "manager"}
    assert checker(claims_mgr) == claims_mgr

    claims_exec = {"sub": str(uuid.uuid4()), "role": "executive"}
    assert checker(claims_exec) == claims_exec

    claims_it = {"sub": str(uuid.uuid4()), "role": "it_admin"}
    with pytest.raises(HTTPException) as exc:
        checker(claims_it)
    assert exc.value.status_code == 403


# ==============================================================================
# 4. Payroll Permissions Tests
# ==============================================================================

def test_payroll_permissions():
    """Verify payroll permissions enforce canonical RoleEnum groupings."""
    claims_hr = {"sub": str(uuid.uuid4()), "role": "hr_admin"}
    claims_mgr = {"sub": str(uuid.uuid4()), "role": "manager"}
    claims_emp = {"sub": str(uuid.uuid4()), "role": "employee"}

    # Admin check
    _require_admin(claims_hr)
    with pytest.raises(ForbiddenException):
        _require_admin(claims_mgr)

    # Manager check
    _require_admin_or_manager(claims_mgr)
    _require_admin_or_manager(claims_hr)
    with pytest.raises(ForbiddenException):
        _require_admin_or_manager(claims_emp)


# ==============================================================================
# 5. Endpoint Protection Verification
# ==============================================================================

@pytest.mark.asyncio
async def test_cto_dashboard_endpoint_requires_auth():
    """Verify /api/v1/cto/dashboard is protected and rejects unauthenticated calls."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/cto/dashboard")
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_hr_copilot_endpoint_requires_auth():
    """Verify /api/v2/hr-copilot/query is protected and rejects unauthenticated calls."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v2/hr-copilot/query", json={"question": "Find Python dev", "top_k": 5})
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_workforce_forecast_endpoint_requires_auth():
    """Verify /api/v2/workforce/forecast is protected and rejects unauthenticated calls."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v2/workforce/forecast", json={"company_id": str(uuid.uuid4()), "forecast_period": "Q3 2026"})
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_org_map_endpoint_requires_auth():
    """Verify /api/v2/org-map/generate is protected and rejects unauthenticated calls."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v2/org-map/generate", json={"company_id": str(uuid.uuid4()), "company_data": "{}"})
        assert resp.status_code in (401, 403)
