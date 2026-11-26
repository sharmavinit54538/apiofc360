"""Tests for one-time email OTP verification, permanent verified status, and route/security guards."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import HTTPException, Request, Response

from app.api.auth import verify_email as verify_email_endpoint
from app.api.settings import ProfilePayload, update_profile
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.security import hash_password
from app.models.otp import OTP
from app.models.user import User
from app.models.user.role import UserRole
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import LoginRequest, ResendOTPRequest, VerifyEmailRequest
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.utils.otp import OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION, hash_otp


def _build_service() -> tuple[AuthService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_tokens = AsyncMock()
    mock_tokens.generate_auth_tokens = AsyncMock(return_value=("access.jwt", "refresh.jwt", 900))
    svc = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_tokens,
    )
    return svc, mock_session, mock_repo, mock_email, mock_tokens


@pytest.mark.asyncio
async def test_repository_update_user_verification_sets_active_and_clears_token():
    """update_user_verification must set account_status='ACTIVE', is_verified=True, is_active=True, and clear token."""
    mock_session = AsyncMock()
    repo = AuthRepository(session=mock_session)
    user_id = uuid.uuid4()

    await repo.update_user_verification(user_id)

    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "account_status" in compiled
    assert "is_verified" in compiled
    assert "is_active" in compiled
    assert "email_verified_at" in compiled
    assert "email_verification_token" in compiled


@pytest.mark.asyncio
async def test_verify_email_otp_once_sets_active_invalidates_otps_and_blocks_reuse():
    """Verifying registration OTP marks user permanently verified & ACTIVE, invalidates OTPs, and blocks reuse."""
    svc, mock_session, mock_repo, mock_email, _ = _build_service()
    user_id = uuid.uuid4()
    raw_otp = "482910"
    now = datetime.now(timezone.utc)

    user = User(
        id=user_id,
        name="Alex HR",
        email="alex@company.com",
        phone="9876543210",
        password_hash=hash_password("Password@123"),
        role=UserRole.HR_ADMIN,
        account_status="PENDING_EMAIL_VERIFICATION",
        is_verified=False,
        is_active=False,
        onboarding_completed=False,
    )
    otp_record = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hash_otp(otp=raw_otp, user_id=user_id, purpose="email_verification"),
        purpose="email_verification",
        expires_at=now + timedelta(minutes=10),
        attempts=0,
        is_used=False,
    )

    mock_repo.get_user_by_email.return_value = user
    mock_repo.get_latest_otp.return_value = otp_record
    mock_repo.consume_otp_atomic.return_value = True

    verified_user = await svc.verify_email(VerifyEmailRequest(email="alex@company.com", otp=raw_otp))

    assert verified_user is user
    assert user.is_verified is True
    assert user.is_active is True
    assert user.account_status == "ACTIVE"
    assert user.email_verified_at is not None
    mock_repo.consume_otp_atomic.assert_awaited_once_with(otp_record.id)
    mock_repo.update_user_verification.assert_awaited_once_with(user_id)
    mock_repo.invalidate_all_user_otps.assert_any_await(user_id, "email_verification")
    mock_repo.invalidate_all_user_otps.assert_any_await(user_id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)
    mock_email.send_welcome_email.assert_awaited_once()

    # Subsequent login for verified account must NOT request email OTP again
    mock_repo.get_user_by_identifier.return_value = user
    mock_repo.create_otp.reset_mock()
    mock_email.send_login_verification_otp_email.reset_mock()
    with (
        patch("app.core.redis_client.redis_client.is_account_locked", new=AsyncMock(return_value=(False, 0))),
        patch("app.core.redis_client.redis_client.clear_failed_logins", new=AsyncMock()),
    ):
        logged_user, access_tok, refresh_tok, expires_in, requires_ver = await svc.login(
            LoginRequest(identifier="alex@company.com", password="Password@123")
        )

    assert logged_user is user
    assert requires_ver is False
    assert access_tok == "access.jwt"
    assert refresh_tok == "refresh.jwt"
    assert expires_in == 900
    mock_repo.create_otp.assert_not_called()
    mock_email.send_login_verification_otp_email.assert_not_called()

    # Reusing the same OTP or re-verifying already verified account must fail
    with pytest.raises(AppException) as reuse_exc:
        await svc.verify_email(VerifyEmailRequest(email="alex@company.com", otp=raw_otp))
    assert reuse_exc.value.status_code == 400
    assert reuse_exc.value.code == "EMAIL_ALREADY_VERIFIED"


@pytest.mark.asyncio
async def test_resend_endpoints_reject_already_verified_accounts():
    """Both resend_otp and resend_email_otp must block already-verified accounts without creating/sending OTPs."""
    svc, _, mock_repo, mock_email, _ = _build_service()
    user_id = uuid.uuid4()
    verified_user = User(
        id=user_id,
        name="Verified User",
        email="verified@company.com",
        phone="9876543210",
        password_hash=hash_password("Password@123"),
        role=UserRole.HR_ADMIN,
        account_status="ACTIVE",
        is_verified=True,
        is_active=True,
        is_deleted=False,
    )
    mock_repo.get_user_by_email.return_value = verified_user

    with pytest.raises(AppException) as exc1:
        await svc.resend_otp(ResendOTPRequest(email="verified@company.com"))
    assert exc1.value.code == "EMAIL_ALREADY_VERIFIED"

    otp_id = uuid.uuid4()
    mock_repo.get_otp_by_id.return_value = OTP(
        id=otp_id,
        user_id=user_id,
        otp_hash="hash",
        purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    mock_repo.get_user_by_id.return_value = verified_user

    with pytest.raises(AppException) as exc2:
        await svc.resend_email_otp(verification_id=str(otp_id), email="verified@company.com")
    assert exc2.value.code == "EMAIL_ALREADY_VERIFIED"
    mock_repo.create_otp.assert_not_called()
    mock_email.send_verification_email.assert_not_called()
    mock_email.send_login_verification_otp_email.assert_not_called()


@pytest.mark.asyncio
async def test_verify_email_rejects_expired_and_exhausted_otp_without_silent_resend():
    """Expired OTPs fail cleanly and exhausted attempts invalidate the OTP without silently bypassing cooldown."""
    svc, mock_session, mock_repo, mock_email, _ = _build_service()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="pending@company.com",
        is_verified=False,
        is_deleted=False,
        account_status="PENDING_EMAIL_VERIFICATION",
    )
    mock_repo.get_user_by_email.return_value = user

    # Expired OTP
    mock_repo.get_latest_otp.return_value = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hash_otp(otp="111111", user_id=user_id, purpose="email_verification"),
        purpose="email_verification",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        attempts=0,
        is_used=False,
    )
    with pytest.raises(AppException) as exp_exc:
        await svc.verify_email(VerifyEmailRequest(email="pending@company.com", otp="111111"))
    assert exp_exc.value.code == "OTP_EXPIRED"

    # Exhausted attempt reaches OTP_MAX_ATTEMPTS -> invalidates OTP, does NOT auto-generate/send new OTP
    mock_repo.get_latest_otp.return_value = OTP(
        id=uuid.uuid4(),
        user_id=user_id,
        otp_hash=hash_otp(otp="222222", user_id=user_id, purpose="email_verification"),
        purpose="email_verification",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        attempts=settings.OTP_MAX_ATTEMPTS - 1,
        is_used=False,
    )
    mock_repo.increment_otp_attempts.return_value = settings.OTP_MAX_ATTEMPTS

    with pytest.raises(AppException) as max_exc:
        await svc.verify_email(VerifyEmailRequest(email="pending@company.com", otp="999999"))
    assert max_exc.value.code == "OTP_MAX_ATTEMPTS"
    mock_repo.invalidate_all_user_otps.assert_awaited_with(user_id, "email_verification")
    mock_repo.create_otp.assert_not_called()
    mock_email.send_verification_email.assert_not_called()


@pytest.mark.asyncio
async def test_verify_email_login_otp_flow_persists_active_and_blocks_subsequent_reuse():
    """Unverified login OTP verification activates account_status='ACTIVE', invalidates OTPs, and blocks reuse."""
    svc, _, mock_repo, _, _ = _build_service()
    user_id = uuid.uuid4()
    otp_id = uuid.uuid4()
    raw_otp = "654321"
    user = User(
        id=user_id,
        name="Unverified HR",
        email="unv@company.com",
        phone="9876543210",
        role=UserRole.HR_ADMIN,
        account_status="PENDING_EMAIL_VERIFICATION",
        is_verified=False,
        is_active=False,
        is_deleted=False,
    )
    otp_record = OTP(
        id=otp_id,
        user_id=user_id,
        otp_hash=hash_otp(otp=raw_otp, user_id=user_id, purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION),
        purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        attempts=0,
        is_used=False,
    )

    mock_repo.get_otp_by_id.return_value = otp_record
    mock_repo.get_user_by_id.return_value = user
    mock_repo.consume_otp_atomic.return_value = True

    scalar_result = MagicMock()
    scalar_result.scalars.return_value.first.return_value = user
    svc.session.execute = AsyncMock(return_value=scalar_result)

    res_user, access_tok, refresh_tok, expires_in = await svc.verify_email_otp(
        verification_id=str(otp_id),
        otp=raw_otp,
    )
    assert res_user is user
    assert access_tok == "access.jwt"
    assert refresh_tok == "refresh.jwt"
    assert expires_in == 900
    mock_repo.update_user_verification.assert_awaited_once_with(user_id)
    mock_repo.invalidate_all_user_otps.assert_any_await(user_id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)

    # Already-verified user cannot reuse a login OTP
    user.is_verified = True
    otp_record.is_used = False
    with pytest.raises(AppException) as dup_exc:
        await svc.verify_email_otp(verification_id=str(otp_id), otp=raw_otp)
    assert dup_exc.value.code == "EMAIL_ALREADY_VERIFIED"


@pytest.mark.asyncio
async def test_verify_email_route_returns_session_tokens_and_onboarding_status():
    """POST /verify-email returns authenticated tokens and onboarding_completed when AuthService returns User."""
    user = User(
        id=uuid.uuid4(),
        name="New Owner",
        email="owner@company.com",
        phone="9876543210",
        role=UserRole.HR_ADMIN,
        account_status="ACTIVE",
        is_verified=True,
        is_active=True,
        onboarding_completed=False,
        email_verified_at=datetime.now(timezone.utc),
        company_id=uuid.uuid4(),
    )
    mock_auth_svc = AsyncMock()
    mock_auth_svc.session = AsyncMock()
    mock_company_res = MagicMock()
    mock_company_res.scalar_one_or_none.return_value = "Acme Corp"
    mock_auth_svc.session.execute = AsyncMock(return_value=mock_company_res)
    mock_auth_svc.verify_email = AsyncMock(return_value=user)
    mock_token_svc = AsyncMock()
    mock_token_svc.generate_auth_tokens = AsyncMock(return_value=("acc.tok", "ref.tok", 900))

    scope = {"type": "http", "headers": [(b"origin", b"http://localhost:5173")], "client": ("127.0.0.1", 5000)}
    request = Request(scope)
    response = Response()

    res = await verify_email_endpoint(
        payload=VerifyEmailRequest(email="owner@company.com", otp="123456"),
        request=request,
        response=response,
        auth_service=mock_auth_svc,
        token_service=mock_token_svc,
    )

    assert res.success is True
    assert res.data is not None
    assert res.data.access_token == "acc.tok"
    assert res.data.user is not None
    assert res.data.user.is_verified is True
    assert res.data.user.is_email_verified is True
    assert res.data.user.account_status == "ACTIVE"
    assert res.data.user.onboarding_completed is False


@pytest.mark.asyncio
async def test_settings_profile_blocks_unverified_email_change_and_account_profile_exposes_verified_fields():
    """Direct email overwrite via /settings/profile must fail; /me must include verification timestamp."""
    user = User(
        id=uuid.uuid4(),
        name="Test User",
        email="original@company.com",
        role=UserRole.HR_ADMIN,
        is_active=True,
        is_verified=True,
        email_verified_at=datetime.now(timezone.utc),
        account_status="ACTIVE",
        onboarding_completed=True,
    )
    mock_session = AsyncMock()
    user_res = MagicMock()
    user_res.scalar_one_or_none.return_value = user
    emp_res = MagicMock()
    emp_res.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(side_effect=[user_res, emp_res])

    with pytest.raises(AppException) as exc:
        await update_profile(
            payload=ProfilePayload(email="hacker@evil.com"),
            claims={"sub": str(user.id), "role": "hr_admin"},
            session=mock_session,
        )
    assert exc.value.status_code == 400
    assert user.email == "original@company.com"

    mock_repo = AsyncMock()
    mock_repo.get_user_by_id.return_value = user
    acct = AccountService(session=AsyncMock(), auth_repository=mock_repo, email_service=AsyncMock())
    profile = await acct.get_profile(user.id)
    assert profile.is_verified is True
    assert profile.is_email_verified is True
    assert profile.email_verified_at == user.email_verified_at
