"""Comprehensive tests for OFC360 User Hierarchy and Registration/Verification flow."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException
from app.core.security import hash_password, verify_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.otp import OTP
from app.models.user import User, UserRole, UserAccountStatus
from app.schemas.auth import LoginRequest, RegisterRequest, ResendOTPRequest, VerifyEmailRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio(loop_scope="session")
async def test_public_registration_forces_hr_admin_and_strips_injected_role():
    """Test that public registration strictly creates HR_ADMIN and ignores/strips client role injection."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_repo.get_user_by_email.return_value = None
    mock_repo.get_user_by_phone.return_value = None

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    # Attempt to inject super_admin role into payload
    malicious_payload_data = {
        "name": "Jane Doe",
        "company_name": "Acme Inc",
        "email": "jane@acme.com",
        "password": "Password@123",
        "phone": "9876543210",
        "role": "super_admin",
        "user_role": "SUPER_ADMIN",
        "is_super_admin": True,
    }
    with pytest.raises(ValidationError):
        payload = RegisterRequest.model_validate(malicious_payload_data)

    # Let's use a safe payload to test that the rest of the flow works
    safe_payload_data = malicious_payload_data.copy()
    safe_payload_data.pop("role")
    safe_payload_data.pop("user_role")
    safe_payload_data.pop("is_super_admin")
    payload = RegisterRequest.model_validate(safe_payload_data)

    with patch("app.utils.employee.generate_employee_id", new=AsyncMock(return_value="EMP-202608-0001")):
        await service.register_user(payload)

    added_objects = [c.args[0] for c in mock_session.add.call_args_list]

    # Verify User created as HR_ADMIN, NOT super_admin
    users = [obj for obj in added_objects if isinstance(obj, User)]
    assert len(users) == 1
    user = users[0]
    assert user.role == UserRole.HR_ADMIN
    assert user.role != UserRole.SUPER_ADMIN
    assert user.account_status == UserAccountStatus.PENDING_EMAIL_VERIFICATION.value
    assert user.is_active is False
    assert user.is_verified is False
    assert user.email_verification_token is not None

    # Verify Employee role is hr_admin
    employees = [obj for obj in added_objects if isinstance(obj, Employee)]
    assert len(employees) == 1
    employee = employees[0]
    assert employee.role == "hr_admin"


@pytest.mark.asyncio(loop_scope="session")
async def test_email_verification_via_token_activates_account():
    """Test that email verification via link token marks user verified, active, and status ACTIVE."""
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

    valid_token = "secure_token_12345"
    test_user = User(
        id=uuid.uuid4(),
        email="hradmin@test.com",
        name="HR Admin",
        role=UserRole.HR_ADMIN,
        account_status="PENDING_EMAIL_VERIFICATION",
        email_verification_token=valid_token,
        email_verification_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        is_verified=False,
        is_active=False,
    )

    mock_repo.get_user_by_verification_token.return_value = test_user

    req = VerifyEmailRequest(token=valid_token)
    await service.verify_email(req)

    mock_repo.update_user_verification.assert_awaited_once_with(test_user.id)
    mock_repo.invalidate_all_user_otps.assert_awaited_once_with(test_user.id, "email_verification")
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="session")
async def test_email_verification_via_otp_activates_account():
    """Test that email verification via 6-digit OTP activates account."""
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

    user_id = uuid.uuid4()
    test_user = User(
        id=user_id,
        email="hradmin@test.com",
        name="HR Admin",
        role=UserRole.HR_ADMIN,
        account_status="PENDING_EMAIL_VERIFICATION",
        is_verified=False,
        is_active=False,
    )

    mock_repo.get_user_by_email.return_value = test_user

    from app.utils.otp import hash_otp
    otp_code = "123456"
    hashed_otp = hash_otp(otp=otp_code, user_id=user_id, purpose="email_verification")

    mock_otp_record = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hashed_otp,
        purpose="email_verification",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempts=0,
        is_used=False,
    )
    mock_repo.get_latest_otp.return_value = mock_otp_record

    req = VerifyEmailRequest(email="hradmin@test.com", otp="123456")
    await service.verify_email(req)

    mock_repo.mark_otp_used.assert_awaited_once_with(mock_otp_record.id)
    mock_repo.update_user_verification.assert_awaited_once_with(user_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_login_blocks_unverified_account_with_email_not_verified():
    """Test that login attempt on unverified account raises 403 EMAIL_NOT_VERIFIED."""
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

    test_user = User(
        id=uuid.uuid4(),
        email="hradmin@test.com",
        phone="9876543210",
        password_hash=hash_password("Password@123"),
        role=UserRole.HR_ADMIN,
        account_status="PENDING_EMAIL_VERIFICATION",
        is_verified=False,
        is_active=False,
    )
    mock_repo.get_user_by_identifier.return_value = test_user

    req = LoginRequest(identifier="hradmin@test.com", password="Password@123")
    with pytest.raises(AppException) as exc_info:
        await service.login(req)

    assert exc_info.value.status_code == 403
    assert "verify your email" in exc_info.value.message.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_login_blocks_inactive_account_with_account_inactive():
    """Test that login attempt on suspended or inactive account raises 403 ACCOUNT_INACTIVE."""
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

    test_user = User(
        id=uuid.uuid4(),
        email="employee@test.com",
        phone="9876543210",
        password_hash=hash_password("Password@123"),
        role=UserRole.EMPLOYEE,
        account_status="SUSPENDED",
        is_verified=True,
        is_active=False,
    )
    mock_repo.get_user_by_identifier.return_value = test_user

    req = LoginRequest(identifier="employee@test.com", password="Password@123")
    with pytest.raises(AppException) as exc_info:
        await service.login(req)

    assert exc_info.value.status_code == 403
    assert "inactive" in exc_info.value.message.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_login_succeeds_for_verified_active_hr_admin():
    """Test that login succeeds for verified active HR Admin and issues tokens."""
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

    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    test_user = User(
        id=user_id,
        company_id=company_id,
        email="hradmin@test.com",
        name="HR Admin",
        phone="9876543210",
        password_hash=hash_password("Password@123"),
        role=UserRole.HR_ADMIN,
        account_status="ACTIVE",
        is_verified=True,
        is_active=True,
    )
    mock_repo.get_user_by_identifier.return_value = test_user
    mock_token_svc.generate_auth_tokens.return_value = ("mock_access_token", "mock_refresh_token", 900)

    req = LoginRequest(identifier="hradmin@test.com", password="Password@123")
    user, access_tok, refresh_tok, exp = await service.login(req)

    assert user.id == user_id
    assert user.role == UserRole.HR_ADMIN
    assert access_tok == "mock_access_token"
    assert refresh_tok == "mock_refresh_token"
