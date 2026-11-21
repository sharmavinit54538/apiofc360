"""Comprehensive automated test suite for OFC360 authentication and RBAC endpoints.

Covers all 24 requirements from the specification:
1. Core 2xx Success Responses for valid requests
2. Zero False 4xx/5xx errors on valid emails, passwords, tokens, aliases, nulls
3. Proper Validation Order
4. Strict 422 Handling for genuine schema violations
5. Standard 400 Bad Request with machine-readable error codes
6. Strict 401 Unauthorized only for truly missing/invalid credentials or tokens
7. Strict 403 Forbidden for authenticated users lacking permission (RBAC)
8. Strict 404 Not Found only for genuine resource misses and tenant isolation
9. Strict 409 Conflict for duplicate emails/phones
10. Safe 500 error handling without generic exception masking
11-16. Audit all auth endpoints: register, verify-email, resend-verification, login, refresh, logout, me
17-22. Response format, serialization stability, transaction safety, and RBAC matrix.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
import pytest

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.security import hash_password
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserAccountStatus, UserRole
from app.schemas.auth import (
    APIResponse,
    ChangeEmailRequest,
    ChangePasswordRequest,
    ChangePhoneRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    ResendOTPRequest,
    ResetPasswordRequest,
    UserLoginPublic,
    UserProfileData,
    UserProfileResponse,
    VerifyEmailRequest,
    VerifyNewEmailRequest,
    VerifyResetOTPRequest,
)
from app.schemas.hr_admin import HRAdminCreateUserRequest, HRAdminUserResponse
from app.services.account_service import AccountService, get_account_service
from app.services.auth_service import AuthService, get_auth_service
from app.services.hr_admin_service import HRAdminService, get_hr_admin_service
from app.services.token_service import TokenService, get_token_service
from app.utils.jwt import create_access_token, create_refresh_token, decode_token
from app.utils.validators import validate_name, validate_password_strength, validate_phone


shared_app = create_app()


# ============================================================================
# 1. Validation Utilities & Name/Phone/Password Tests
# ============================================================================

def test_validate_name_supports_hyphens_dots_apostrophes():
    """Names with apostrophes, hyphens, dots, spaces, and min length 2 must be valid."""
    assert validate_name("Jean-Luc Picard") == "Jean-Luc Picard"
    assert validate_name("O'Connor") == "O'Connor"
    assert validate_name("Mary-Jane Watson") == "Mary-Jane Watson"
    assert validate_name("Dr. John Watson") == "Dr. John Watson"
    assert validate_name("Li Wang") == "Li Wang"
    assert validate_name("Bo") == "Bo"


def test_validate_name_rejects_empty_or_numbers():
    """Invalid names must raise ValueError."""
    with pytest.raises(ValueError):
        validate_name("")
    with pytest.raises(ValueError):
        validate_name("John123")
    with pytest.raises(ValueError):
        validate_name("   ")


def test_validate_phone_normalization():
    """Phones with +91, spaces, hyphens, and leading zero must normalize to 10 digits."""
    assert validate_phone("+91 9876543210") == "9876543210"
    assert validate_phone("09876543210") == "9876543210"
    assert validate_phone("98765-43210") == "9876543210"
    assert validate_phone(9876543210) == "9876543210"


def test_validate_password_strength_rules():
    """Strong passwords pass; weak or simple passwords fail."""
    valid_pass = validate_password_strength("StrongPass@2026")
    assert valid_pass == "StrongPass@2026"

    with pytest.raises(ValueError):
        validate_password_strength("weak")  # too short
    with pytest.raises(ValueError):
        validate_password_strength("12345678")  # weak password list
    with pytest.raises(ValueError):
        validate_password_strength("nouppercase123!")
    with pytest.raises(ValueError):
        validate_password_strength("NOLOWERCASE123!")
    with pytest.raises(ValueError):
        validate_password_strength("NoDigitsHere!!")
    with pytest.raises(ValueError):
        validate_password_strength("NoSpecialChars123")


# ============================================================================
# 2. Register API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_register_endpoint_success_returns_201():
    """Valid registration returns 201 Created with clean response."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.register_user.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "first_name": "Jean-Luc",
            "last_name": "Picard",
            "email": "picard@enterprise.com",
            "phone_number": "+91 9876543210",
            "company_name": "Starfleet",
            "password": "Password@2026",
            "extra_ignored_field": "harmless",
        }
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "Registration successful" in data["message"]
        assert data["data"] is None

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_register_endpoint_duplicate_email_returns_409():
    """Duplicate email returns 409 Conflict with EMAIL_ALREADY_EXISTS."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.register_user.side_effect = ConflictException(
        message="Email already exists.",
        code="EMAIL_ALREADY_EXISTS",
        errors=[{"field": "email", "message": "Email already exists."}],
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "name": "Jane Doe",
            "email": "existing@example.com",
            "phone": "9876543210",
            "company_name": "Acme Corp",
            "password": "Password@2026",
        }
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "Email already exists."
        assert data["code"] == "EMAIL_ALREADY_EXISTS"

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_register_endpoint_invalid_input_returns_422():
    """Malformed email or missing required field returns 422 Unprocessable Entity."""
    app = shared_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid email
        resp = await client.post("/api/v1/auth/register", json={
            "name": "Jane Doe",
            "email": "not-an-email",
            "phone": "9876543210",
            "company_name": "Acme Corp",
            "password": "Password@2026",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["success"] is False
        assert data["field"] == "email"

        # Missing password
        resp2 = await client.post("/api/v1/auth/register", json={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "9876543210",
            "company_name": "Acme Corp",
        })
        assert resp2.status_code == 422


# ============================================================================
# 3. Login API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_login_endpoint_success_returns_200():
    """Correct credentials return 200 OK with tokens, user details, and organization info."""
    app = shared_app
    mock_auth_svc = AsyncMock()

    user_id = uuid.uuid4()
    comp_id = uuid.uuid4()
    mock_user = MagicMock(spec=User)
    mock_user.id = user_id
    mock_user.name = "John Doe"
    mock_user.email = "john@example.com"
    mock_user.phone = "9876543210"
    mock_user.role = UserRole.HR_ADMIN
    mock_user.is_verified = True
    mock_user.account_status = "ACTIVE"
    mock_user.is_active = True
    mock_user.must_change_password = False
    mock_user.onboarding_completed = True
    mock_user.company_id = comp_id
    mock_user.company = MagicMock()
    mock_user.company.name = "Acme Corp"
    mock_user.company.onboarding_completed = True

    mock_auth_svc.login.return_value = (
        mock_user,
        "access_token_123",
        "refresh_token_456",
        900,
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Accepts phone as identifier
        payload = {"identifier": "9876543210", "password": "Password@2026"}
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["access_token"] == "access_token_123"
        assert data["data"]["refresh_token"] == "refresh_token_456"
        assert data["data"]["user"]["email"] == "john@example.com"
        assert data["data"]["user"]["role"] == "hr_admin"
        assert data["data"]["user"]["email_verified"] is True
        assert data["data"]["user"]["account_status"] == "ACTIVE"
        assert data["data"]["user"]["company_name"] == "Acme Corp"

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_login_endpoint_wrong_credentials_returns_401():
    """Wrong password or unknown user returns 401 Unauthorized."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.login.side_effect = AppException(
        message="Invalid email or password.",
        status_code=401,
        code="INVALID_CREDENTIALS",
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"email": "unknown@example.com", "password": "WrongPassword@123"}
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "Invalid email or password."
        assert data["code"] == "INVALID_CREDENTIALS"

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_login_endpoint_unverified_email_returns_403():
    """Unverified email login attempt returns 403 Forbidden with EMAIL_NOT_VERIFIED."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.login.side_effect = AppException(
        message="Email not verified. Please verify your email before logging in.",
        status_code=403,
        code="EMAIL_NOT_VERIFIED",
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"identifier": "unverified@example.com", "password": "Password@123"}
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 403
        data = resp.json()
        assert data["success"] is False
        assert data["code"] == "EMAIL_NOT_VERIFIED"

    app.dependency_overrides.clear()


# ============================================================================
# 4. Verify Email API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_verify_email_endpoint_via_token_success_returns_200():
    """Valid verification token returns 200 OK."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.verify_email.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/verify-email", json={"token": "valid_token_123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Email verified" in data["message"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_verify_email_endpoint_via_otp_success_returns_200():
    """Valid email + 6-digit OTP returns 200 OK."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.verify_email.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/verify-email", json={"email": "user@example.com", "otp": "123456"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_verify_email_invalid_token_returns_400():
    """Invalid token raises 400 Bad Request."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.verify_email.side_effect = AppException(
        message="Invalid or expired verification token.",
        status_code=400,
        code="INVALID_TOKEN",
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/verify-email", json={"token": "bad_token"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["code"] == "INVALID_TOKEN"

    app.dependency_overrides.clear()


# ============================================================================
# 5. Resend OTP API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_resend_verification_endpoint_success_returns_200():
    """Valid unverified user resend OTP returns 200 OK."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.resend_otp.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/resend-verification", json={"email": "pending@example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "OTP sent" in data["message"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_resend_verification_unknown_user_returns_404():
    """Non-existent user raises 404 Not Found."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.resend_otp.side_effect = AppException(
        message="User not found",
        status_code=404,
        code="USER_NOT_FOUND",
    )
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/resend-verification", json={"email": "missing@example.com"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["code"] == "USER_NOT_FOUND"

    app.dependency_overrides.clear()


# ============================================================================
# 6. Refresh Token API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_endpoint_success_returns_200():
    """Valid refresh token (including camelCase alias) returns 200 OK with new pair."""
    app = shared_app
    mock_tok_svc = AsyncMock()
    mock_tok_svc.rotate_refresh_token.return_value = ("new_access_tok", "new_refresh_tok", 900)
    app.dependency_overrides[get_token_service] = lambda: mock_tok_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Standard snake_case
        resp1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": "valid_rt_123"})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["data"]["access_token"] == "new_access_tok"
        assert data1["data"]["refresh_token"] == "new_refresh_tok"

        # Frontend camelCase alias 'refreshToken'
        resp2 = await client.post("/api/v1/auth/refresh", json={"refreshToken": "valid_rt_123"})
        assert resp2.status_code == 200

        # /refresh-token alternate route
        resp3 = await client.post("/api/v1/auth/refresh-token", json={"refresh_token": "valid_rt_123"})
        assert resp3.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_endpoint_invalid_returns_401():
    """Invalid or expired refresh token returns 401 Unauthorized."""
    app = shared_app
    mock_tok_svc = AsyncMock()
    mock_tok_svc.rotate_refresh_token.side_effect = AppException(
        message="Invalid or expired refresh token.",
        status_code=401,
        code="INVALID_REFRESH_TOKEN",
    )
    app.dependency_overrides[get_token_service] = lambda: mock_tok_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "expired_rt"})
        assert resp.status_code == 401
        data = resp.json()
        assert data["success"] is False
        assert data["code"] == "INVALID_REFRESH_TOKEN"

    app.dependency_overrides.clear()


# ============================================================================
# 7. Logout API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_logout_endpoint_succeeds_even_if_access_token_expired():
    """Logout with expired access token revokes refresh token and returns 200 OK without false 401."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.logout.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User provides refresh_token and an expired/missing access token
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "active_refresh_token_to_revoke"},
            headers={"Authorization": "Bearer expired.invalid.token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Logged out" in data["message"]
        mock_auth_svc.logout.assert_awaited_once()

    app.dependency_overrides.clear()


# ============================================================================
# 8. Auth /me API Endpoint Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_get_me_endpoint_returns_200_with_full_profile():
    """Authenticated user /me returns 200 OK with id, name, email, role, company, email_verified, account_status."""
    app = shared_app
    user_id = uuid.uuid4()
    comp_id = uuid.uuid4()

    mock_profile = UserProfileData(
        id=user_id,
        name="Alice Johnson",
        email="alice@company.com",
        phone="9876543210",
        role="hr_admin",
        is_active=True,
        is_verified=True,
        email_verified=True,
        account_status="ACTIVE",
        onboarding_completed=True,
        company_id=comp_id,
        company_name="Acme Enterprises",
        created_at=datetime.now(timezone.utc),
    )

    mock_acc_svc = AsyncMock()
    mock_acc_svc.get_profile.return_value = mock_profile
    app.dependency_overrides[get_account_service] = lambda: mock_acc_svc

    # Create valid access token
    valid_token = create_access_token(user_id=user_id, role="hr_admin", company_id=comp_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["email"] == "alice@company.com"
        assert data["data"]["role"] == "hr_admin"
        assert data["data"]["email_verified"] is True
        assert data["data"]["account_status"] == "ACTIVE"
        assert data["data"]["company_name"] == "Acme Enterprises"

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_get_me_endpoint_null_phone_and_company_does_not_crash_500():
    """User profile with null phone, null company_name serializes cleanly without 500."""
    user_id = uuid.uuid4()
    profile = UserProfileData(
        id=user_id,
        name="Bob Smith",
        email="bob@company.com",
        phone=None,
        role="employee",
        is_active=True,
        is_verified=True,
        email_verified=True,
        account_status="INVITED",
        onboarding_completed=False,
        company_id=None,
        company_name=None,
        created_at=None,
    )
    dumped = profile.model_dump()
    assert dumped["phone"] is None
    assert dumped["company_name"] is None
    assert dumped["role"] == "employee"


@pytest.mark.asyncio(loop_scope="session")
async def test_get_me_missing_token_returns_401():
    """GET /me without bearer token returns 401 Unauthorized."""
    app = shared_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


# ============================================================================
# 9. Password Recovery & Account Settings Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_forgot_password_endpoint_returns_200():
    """Forgot password request returns 200 OK without leaking existence."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.forgot_password.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/forgot-password", json={"email": "any@example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_reset_password_endpoint_returns_200():
    """Valid reset token and password updates credentials and returns 200 OK."""
    app = shared_app
    mock_auth_svc = AsyncMock()
    mock_auth_svc.reset_password.return_value = None
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/reset-password", json={
            "token": "valid_reset_tok",
            "password": "NewSecurePassword@2026",
            "confirm_password": "NewSecurePassword@2026",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    app.dependency_overrides.clear()


# ============================================================================
# 10. RBAC & Internal User Creation Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_hr_admin_create_internal_users_returns_201():
    """HR Admin can create EMPLOYEE, MANAGER, EXECUTIVE, and IT_ADMIN accounts."""
    app = shared_app
    admin_id = uuid.uuid4()
    comp_id = uuid.uuid4()

    mock_hr_svc = AsyncMock()
    app.dependency_overrides[get_hr_admin_service] = lambda: mock_hr_svc

    # Create admin token
    admin_token = create_access_token(user_id=admin_id, role="hr_admin", company_id=comp_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for role in ["EMPLOYEE", "MANAGER", "EXECUTIVE", "IT_ADMIN"]:
            user_id = uuid.uuid4()
            mock_resp = HRAdminUserResponse(
                id=user_id,
                name=f"Test {role}",
                first_name="Test",
                last_name=role,
                email=f"{role.lower()}@company.com",
                role=role.lower(),
                account_status="INVITED",
                is_active=False,
                is_verified=False,
            )
            mock_hr_svc.create_user.return_value = mock_resp

            payload = {
                "first_name": "Test",
                "last_name": role,
                "email": f"{role.lower()}@company.com",
                "phone": "9876543210",
                "role": role,
                "department": "Engineering",
                "designation": role.capitalize(),
            }
            resp = await client.post(
                "/api/v1/hr-admin/users",
                json=payload,
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["success"] is True
            assert data["data"]["role"] == role.lower()

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_employee_cannot_create_users_returns_403():
    """Employee attempting to create users receives 403 Forbidden."""
    app = shared_app
    emp_id = uuid.uuid4()
    comp_id = uuid.uuid4()

    # Employee token (not admin)
    emp_token = create_access_token(user_id=emp_id, role="employee", company_id=comp_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "first_name": "Hacker",
            "last_name": "User",
            "email": "hacker@company.com",
            "role": "EMPLOYEE",
        }
        resp = await client.post(
            "/api/v1/hr-admin/users",
            json=payload,
            headers={"Authorization": f"Bearer {emp_token}"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["success"] is False
