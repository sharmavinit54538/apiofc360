"""Comprehensive test suite for OTP & Sensitive Account Workflow Hardening.

Covers:
1. Atomic single-use invalidation for OTPs (AuthService & AccountService).
2. Atomic single-use invalidation for Password Reset Tokens.
3. Immediate password reset token invalidation upon setting/changing passwords.
4. Mandatory current password re-authentication before staging or updating pending_email.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import status

from app.core.exceptions import AppException
from app.models.otp import OTP
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    VerifyNewEmailRequest,
)
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.utils.otp import hash_otp
from app.utils.security import hash_password


# ==============================================================================
# 1. Atomic Single-Use OTP Invalidation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_repository_consume_otp_atomic():
    """Verify consume_otp_atomic updates is_used and returns True on first call, False on second."""
    mock_session = AsyncMock()
    repo = AuthRepository(session=mock_session)
    otp_id = uuid.uuid4()

    # Simulate first execution: 1 row matched and updated
    mock_res_1 = MagicMock()
    mock_res_1.rowcount = 1
    mock_session.execute.return_value = mock_res_1

    consumed_first = await repo.consume_otp_atomic(otp_id)
    assert consumed_first is True

    # Simulate second execution (already used): 0 rows updated
    mock_res_2 = MagicMock()
    mock_res_2.rowcount = 0
    mock_session.execute.return_value = mock_res_2

    consumed_second = await repo.consume_otp_atomic(otp_id)
    assert consumed_second is False


@pytest.mark.asyncio
async def test_verify_email_otp_atomic_single_use_rejection():
    """Verify verify_email_otp rejects already consumed or concurrently used OTP."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    raw_otp = "123456"
    purpose = "email_verification"
    now = datetime.now(timezone.utc)

    mock_user = User(id=user_id, email="test@example.com", is_verified=False, name="Test User")
    mock_otp_record = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hash_otp(otp=raw_otp, user_id=user_id, purpose=purpose),
        purpose=purpose,
        expires_at=now + timedelta(minutes=10),
        attempts=0,
        is_used=False,
    )

    mock_auth_repo.get_user_by_email.return_value = mock_user
    mock_auth_repo.get_latest_otp.return_value = mock_otp_record

    # First attempt: consume_otp_atomic returns False (simulate concurrent race where another thread consumed it)
    mock_auth_repo.consume_otp_atomic.return_value = False

    payload = VerifyEmailRequest(email="test@example.com", otp=raw_otp)

    with pytest.raises(AppException) as exc_info:
        await service.verify_email(payload)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already been used" in exc_info.value.message


# ==============================================================================
# 2. Atomic Single-Use Password Reset Token Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_repository_consume_password_reset_token_atomic():
    """Verify consume_password_reset_token_atomic succeeds only once."""
    mock_session = AsyncMock()
    repo = AuthRepository(session=mock_session)
    token_id = uuid.uuid4()

    # First call -> 1 row updated
    mock_res_1 = MagicMock()
    mock_res_1.rowcount = 1
    mock_session.execute.return_value = mock_res_1

    assert await repo.consume_password_reset_token_atomic(token_id) is True

    # Second call -> 0 rows updated
    mock_res_2 = MagicMock()
    mock_res_2.rowcount = 0
    mock_session.execute.return_value = mock_res_2

    assert await repo.consume_password_reset_token_atomic(token_id) is False


@pytest.mark.asyncio
async def test_reset_password_atomic_consumption_and_token_invalidation():
    """Verify reset_password atomically consumes token and purges all user reset tokens and OTPs."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    token_id = uuid.uuid4()
    mock_user = User(id=user_id, email="user@example.com", password_hash=hash_password("OldPassword@123"), is_deleted=False)

    now = datetime.now(timezone.utc)
    mock_token_record = PasswordResetToken(
        id=token_id,
        user_id=user_id,
        role="EMPLOYEE",
        hashed_token="hashed_token_val",
        expires_at=now + timedelta(hours=1),
        used_at=None,
    )
    mock_token_record.user = mock_user

    mock_auth_repo.get_user_by_email.return_value = mock_user
    mock_auth_repo.get_password_reset_token.return_value = mock_token_record
    mock_auth_repo.consume_password_reset_token_atomic.return_value = True

    payload = ResetPasswordRequest(email="user@example.com", reset_token="raw_reset_token", new_password="NewPassword@2026!", confirm_password="NewPassword@2026!")

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new_callable=AsyncMock) as mock_revoke_tokens:
        await service.reset_password(payload)

        # Verify atomic consumption
        mock_auth_repo.consume_password_reset_token_atomic.assert_awaited_once_with(token_id)
        # Verify invalidation of remaining tokens & OTPs
        mock_auth_repo.invalidate_all_user_password_resets.assert_awaited_once_with(user_id)
        mock_auth_repo.invalidate_all_user_otps.assert_awaited_once_with(user_id)
        # Verify sessions revoked
        mock_auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="PASSWORD_RESET")
        mock_revoke_tokens.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_reset_password_rejects_replayed_token():
    """Verify reset_password immediately rejects a replayed token if consume_password_reset_token_atomic fails."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    token_id = uuid.uuid4()
    mock_user = User(id=user_id, email="user@example.com", password_hash=hash_password("OldPassword@123"), is_deleted=False)

    now = datetime.now(timezone.utc)
    mock_token_record = PasswordResetToken(
        id=token_id,
        user_id=user_id,
        role="EMPLOYEE",
        hashed_token="hashed_token_val",
        expires_at=now + timedelta(hours=1),
        used_at=None,
    )
    mock_token_record.user = mock_user

    mock_auth_repo.get_user_by_email.return_value = mock_user
    mock_auth_repo.get_password_reset_token.return_value = mock_token_record
    # Simulate concurrent race where another process consumed it
    mock_auth_repo.consume_password_reset_token_atomic.return_value = False

    payload = ResetPasswordRequest(email="user@example.com", reset_token="raw_reset_token", new_password="NewPassword@2026!", confirm_password="NewPassword@2026!")

    with pytest.raises(AppException) as exc_info:
        await service.reset_password(payload)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already been used" in exc_info.value.message


# ==============================================================================
# 3. Mandatory Re-Authentication on Email Change Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_change_email_requires_correct_current_password():
    """Verify change_email fails with 401 when current password is wrong or empty, without staging pending_email."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    service = AccountService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    user_id = uuid.uuid4()
    real_pw = "CorrectPassword@123"
    mock_user = User(id=user_id, email="current@example.com", password_hash=hash_password(real_pw), name="Alex")
    mock_auth_repo.get_user_by_id.return_value = mock_user

    # 1. Attempt with incorrect password
    payload_wrong = ChangeEmailRequest(new_email="new@example.com", password="WrongPassword@999")

    with pytest.raises(AppException) as exc_info:
        await service.change_email(user_id, payload_wrong)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Password is incorrect" in exc_info.value.message
    # Verify no pending_email was updated and no OTP created
    mock_auth_repo.update_user_pending_email.assert_not_called()
    mock_auth_repo.create_otp.assert_not_called()
    mock_email_service.send_email_change_otp.assert_not_called()


@pytest.mark.asyncio
async def test_change_email_succeeds_with_valid_password():
    """Verify change_email stages pending_email and sends OTP when password re-auth succeeds."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    service = AccountService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    user_id = uuid.uuid4()
    real_pw = "CorrectPassword@123"
    mock_user = User(id=user_id, email="current@example.com", password_hash=hash_password(real_pw), name="Alex")
    mock_auth_repo.get_user_by_id.return_value = mock_user
    mock_auth_repo.get_user_by_email_excluding.return_value = None
    mock_auth_repo.get_latest_otp.return_value = None
    mock_auth_repo.count_email_change_otps.return_value = 0

    payload = ChangeEmailRequest(new_email="newemail@example.com", password=real_pw)

    await service.change_email(user_id, payload)

    mock_auth_repo.update_user_pending_email.assert_awaited_once_with(user_id, "newemail@example.com")
    mock_auth_repo.create_otp.assert_awaited_once()
    mock_email_service.send_email_change_otp.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_new_email_atomic_single_use():
    """Verify verify_new_email atomically consumes OTP and rejects replayed attempts."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock()
    mock_email_service = AsyncMock()

    service = AccountService(
        session=mock_session,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    user_id = uuid.uuid4()
    raw_otp = "654321"
    now = datetime.now(timezone.utc)
    mock_user = User(id=user_id, email="old@example.com", pending_email="new@example.com", name="Alex")

    mock_otp_record = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hash_otp(otp=raw_otp, user_id=user_id, purpose="email_change"),
        purpose="email_change",
        expires_at=now + timedelta(minutes=10),
        attempts=0,
        is_used=False,
    )

    mock_auth_repo.get_user_by_id.return_value = mock_user
    mock_auth_repo.get_latest_otp.return_value = mock_otp_record
    mock_auth_repo.consume_otp_atomic.return_value = True

    payload = VerifyNewEmailRequest(otp=raw_otp)

    # 1. First verification succeeds
    await service.verify_new_email(user_id, payload)
    mock_auth_repo.consume_otp_atomic.assert_awaited_once_with(mock_otp_record.id)
    mock_auth_repo.update_user_email.assert_awaited_once_with(user_id, "new@example.com")

    # 2. Second verification where consume_otp_atomic fails (already used)
    mock_auth_repo.consume_otp_atomic.return_value = False
    with pytest.raises(AppException) as exc_info:
        await service.verify_new_email(user_id, payload)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already been used" in exc_info.value.message
