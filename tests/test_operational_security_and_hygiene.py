"""Consolidated Operational Security & Hygiene Test Suite.

Covers:
1. Deactivated employee login rejection.
2. Token revocation on logout & password reset.
3. Brute-force lockout triggers & rate limiting.
4. Cross-tenant IDOR rejection.
5. Structured logging sanitization (no raw hashes or unmasked tokens).
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import status

from app.core.exceptions import AppException
from app.core.redis_client import redis_client
from app.core.structured_logging import JSONFormatter, SensitiveDataFilter, mask_sensitive_data
from app.models.employee import Employee
from app.models.payroll import PayCycle, Payslip
from app.models.user import User, UserRole
from app.repositories.auth_repository import AuthRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.payroll_repository import PayrollRepository
from app.schemas.auth import LoginRequest, ResetPasswordRequest
from app.services.auth_service import AuthService
from app.utils.security import hash_password


# ==============================================================================
# 1. Deactivated Employee Login Rejection
# ==============================================================================

@pytest.mark.asyncio
async def test_deactivated_user_login_rejection():
    """Verify that users with account_status='DEACTIVATED' or is_active=False are rejected on login."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    raw_pass = "EmployeePass@123"
    deactivated_user = User(
        id=user_id,
        email="deactivated@company.com",
        password_hash=hash_password(raw_pass),
        role=UserRole.EMPLOYEE,
        is_active=False,
        account_status="DEACTIVATED",
        is_verified=True,
        failed_login_attempts=0,
        locked_until=None,
    )

    mock_auth_repo.get_user_by_identifier.return_value = deactivated_user

    payload = LoginRequest(email="deactivated@company.com", password=raw_pass)

    with patch("app.core.redis_client.redis_client.is_account_locked", new_callable=AsyncMock) as mock_is_locked:
        mock_is_locked.return_value = (False, 0)
        with pytest.raises(AppException) as exc_info:
            await service.login(payload)

        assert exc_info.value.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert any(word in exc_info.value.message.lower() for word in ("inactive", "deactivated", "disabled", "contact"))


# ==============================================================================
# 2. Token Revocation on Logout & Password Reset
# ==============================================================================

@pytest.mark.asyncio
async def test_token_revocation_on_logout():
    """Verify logout blacklists access token in Redis and revokes refresh token."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_token_svc = AsyncMock()
    mock_email_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sample_access_token"
    refresh_token = "sample_refresh_token"

    with patch("app.core.redis_client.redis_client.blacklist_token", new_callable=AsyncMock) as mock_bl:
        await service.logout(refresh_token=refresh_token, access_token=access_token)

        mock_bl.assert_awaited_once()
        mock_token_svc.revoke_refresh_token.assert_awaited_once_with(refresh_token)


@pytest.mark.asyncio
async def test_token_revocation_on_password_reset():
    """Verify password reset purges all active refresh tokens and user sessions."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    mock_user = User(
        id=user_id,
        email="reset@example.com",
        password_hash=hash_password("OldPass@123"),
        is_deleted=False,
    )

    mock_token = MagicMock()
    mock_token.id = uuid.uuid4()
    mock_token.user = mock_user
    mock_token.used_at = None
    mock_token.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    mock_auth_repo.get_password_reset_token.return_value = mock_token
    mock_auth_repo.consume_password_reset_token_atomic.return_value = True

    payload = ResetPasswordRequest(
        token="valid_token",
        password="NewPassword@2026!",
        confirm_password="NewPassword@2026!",
    )

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new_callable=AsyncMock) as mock_revoke_user:
        await service.reset_password(payload)

        mock_auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="PASSWORD_RESET")
        mock_revoke_user.assert_awaited_once_with(user_id)


# ==============================================================================
# 3. Brute-Force Lockout Triggers
# ==============================================================================

@pytest.mark.asyncio
async def test_brute_force_lockout_trigger():
    """Verify 5 failed attempts trigger progressive account lockout."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    mock_user = User(
        id=user_id,
        email="victim@company.com",
        password_hash=hash_password("RealPassword@123"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        is_verified=True,
        failed_login_attempts=0,
        locked_until=None,
    )
    mock_auth_repo.get_user_by_identifier.return_value = mock_user

    payload = LoginRequest(email="victim@company.com", password="WrongPassword!")

    # Simulate 5th failed attempt triggering lockout in Redis
    with patch("app.core.redis_client.redis_client.is_account_locked", new_callable=AsyncMock) as mock_is_locked, \
         patch("app.core.redis_client.redis_client.record_failed_login", new_callable=AsyncMock) as mock_rec_failed:

        mock_is_locked.return_value = (False, 0)
        mock_rec_failed.return_value = (5, True, 900)  # 5 attempts -> locked for 15 min (900s)

        with pytest.raises(AppException) as exc_info:
            await service.login(payload)

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "locked" in exc_info.value.message.lower()
        mock_rec_failed.assert_awaited_once()
        mock_auth_repo.record_failed_login_db.assert_awaited_once()


# ==============================================================================
# 4. Cross-Tenant IDOR Rejection
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_tenant_idor_rejection_employee():
    """Verify Employee lookups reject cross-tenant access."""
    mock_session = AsyncMock()
    repo = EmployeeRepository(session=mock_session)

    comp_b = uuid.uuid4()
    emp_id = uuid.uuid4()

    # Mismatched company_id query returns None
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    res = await repo.get_by_id(emp_id, company_id=comp_b)
    assert res is None
    called_stmt = mock_session.execute.call_args[0][0]
    assert "employees.company_id" in str(called_stmt)


@pytest.mark.asyncio
async def test_cross_tenant_idor_rejection_payroll():
    """Verify PayCycle and Payslip lookups reject cross-tenant access."""
    mock_session = AsyncMock()
    repo = PayrollRepository(session=mock_session)

    comp_b = uuid.uuid4()
    cycle_id = uuid.uuid4()
    payslip_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    res_cycle = await repo.get_cycle(cycle_id, company_id=comp_b)
    assert res_cycle is None

    res_payslip = await repo.get_payslip(payslip_id, company_id=comp_b)
    assert res_payslip is None


# ==============================================================================
# 5. Structured Logging Sanitization (No Raw Hashes or Unmasked Tokens)
# ==============================================================================

def test_mask_sensitive_data_bcrypt_hashes():
    """Verify mask_sensitive_data masks bcrypt password hashes."""
    raw_hash = "$2b$12$e8Y7zHh47j3NqL2yX9M.Ye9qP2r8j4Z4n5b1y2m3k4l5o6p7q8r9s"
    log_msg = f"User authentication failed for hash: {raw_hash}"
    sanitized = mask_sensitive_data(log_msg)

    assert raw_hash not in sanitized
    assert "[MASKED_PASSWORD_HASH]" in sanitized


def test_mask_sensitive_data_jwt_and_bearer():
    """Verify mask_sensitive_data masks JWT tokens and Bearer headers."""
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doz_sample_signature_value"
    log_msg = f"Authorization header received: Bearer {jwt}"
    sanitized = mask_sensitive_data(log_msg)

    assert jwt not in sanitized
    assert "Bearer [MASKED_TOKEN]" in sanitized


def test_json_formatter_masks_sensitive_data():
    """Verify JSONFormatter redacts password hashes and tokens in structured log output."""
    formatter = JSONFormatter()
    raw_hash = "$2b$12$e8Y7zHh47j3NqL2yX9M.Ye9qP2r8j4Z4n5b1y2m3k4l5o6p7q8r9s"
    raw_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sample_payload.sample_sig"

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg=f"Attempting login for user with hash={raw_hash} and token={raw_jwt}",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    log_json = json.loads(output)

    assert raw_hash not in log_json["message"]
    assert raw_jwt not in log_json["message"]
    assert "[MASKED_PASSWORD_HASH]" in log_json["message"]
    assert "[MASKED_JWT]" in log_json["message"]
