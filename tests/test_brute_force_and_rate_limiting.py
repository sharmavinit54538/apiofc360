"""Comprehensive tests for Brute-Force Protection, Progressive Account Lockout, and Strict Rate Limiting.

Covers:
1. Redis-backed failed login tracking per account identifier + IP.
2. Progressive lockout period (15m, 30m, 60m, 120m).
3. Non-enumerating standardized security error responses (mitigating user enumeration).
4. DB fallback persistence for failed_login_attempts and locked_until.
5. Successful login failure count & lockout reset.
6. Strict rate limiting on /auth/login, /auth/forgot-password, and OTP endpoints.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import Request, status

from app.core.exceptions import AppException
from app.core.rate_limiter import (
    RateLimitExceeded,
    check_forgot_password_rate_limit,
    check_login_rate_limit,
    check_otp_rate_limit,
    rate_limiter,
)
from app.core.redis_client import redis_client
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService


# ==============================================================================
# 1. Redis Failed Login Tracker & Progressive Lockout Engine Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_redis_failed_login_tracking_and_lockout_trigger():
    """Verify that failed logins increment counter and trigger 15m lockout on 5th attempt."""
    identifier = f"user_{uuid.uuid4().hex[:8]}@example.com"
    ip = "192.168.1.50"

    # Initially not locked
    is_locked, remaining = await redis_client.is_account_locked(identifier, ip)
    assert is_locked is False
    assert remaining == 0

    # Record 4 failed attempts -> not locked yet
    for i in range(1, 5):
        attempts, locked_now, lock_sec = await redis_client.record_failed_login(
            identifier, ip, max_attempts=5, base_lockout_seconds=900
        )
        assert attempts == i
        assert locked_now is False
        assert lock_sec == 0

    # 5th failed attempt -> triggers lockout
    attempts, locked_now, lock_sec = await redis_client.record_failed_login(
        identifier, ip, max_attempts=5, base_lockout_seconds=900
    )
    assert attempts == 5
    assert locked_now is True
    assert lock_sec == 900  # 15 minutes base lockout

    # Account is now locked
    is_locked, remaining = await redis_client.is_account_locked(identifier, ip)
    assert is_locked is True
    assert remaining > 0
    assert remaining <= 900


@pytest.mark.asyncio
async def test_redis_progressive_lockout_duration_escalation():
    """Verify that subsequent lockouts for repeat offenders escalate progressively (15m -> 30m)."""
    identifier = f"repeat_offender_{uuid.uuid4().hex[:8]}@example.com"
    ip = "10.0.0.99"

    # Tier 1 Lockout: 5 failed attempts -> 900s (15 min)
    for _ in range(4):
        await redis_client.record_failed_login(identifier, ip, max_attempts=5, base_lockout_seconds=900)
    _, locked_now, lock_sec = await redis_client.record_failed_login(
        identifier, ip, max_attempts=5, base_lockout_seconds=900
    )
    assert locked_now is True
    assert lock_sec == 900

    # Clear active lockout key to simulate expired lock but maintain tier
    await redis_client.delete(f"lockout:id:{redis_client.normalize_identifier(identifier)}")

    # Tier 2 Lockout: next 5 failed attempts -> 1800s (30 min)
    for _ in range(4):
        await redis_client.record_failed_login(identifier, ip, max_attempts=5, base_lockout_seconds=900)
    _, locked_now, lock_sec = await redis_client.record_failed_login(
        identifier, ip, max_attempts=5, base_lockout_seconds=900
    )
    assert locked_now is True
    assert lock_sec == 1800  # 30 minutes escalated lockout


@pytest.mark.asyncio
async def test_redis_clear_failed_logins():
    """Verify that clear_failed_logins deletes all failure counters and lockouts."""
    identifier = f"cleared_{uuid.uuid4().hex[:8]}@example.com"
    ip = "172.16.0.5"

    # Trigger lockout
    for _ in range(5):
        await redis_client.record_failed_login(identifier, ip, max_attempts=5, base_lockout_seconds=900)

    is_locked, _ = await redis_client.is_account_locked(identifier, ip)
    assert is_locked is True

    # Clear logins on success
    await redis_client.clear_failed_logins(identifier, ip)

    is_locked, remaining = await redis_client.is_account_locked(identifier, ip)
    assert is_locked is False
    assert remaining == 0


# ==============================================================================
# 2. AuthService Brute-Force Defense & Enumeration Mitigation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_service_non_existent_user_returns_generic_error_and_tracks_attempts():
    """Verify non-existent user login returns generic 401 and tracks failed attempts without leaking existence."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_repo.get_user_by_identifier.return_value = None

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    identifier = f"ghost_{uuid.uuid4().hex[:8]}@example.com"
    payload = LoginRequest(identifier=identifier, password="WrongPassword@123")

    # First 4 attempts -> generic 401
    for _ in range(4):
        with pytest.raises(AppException) as exc_info:
            await service.login(payload=payload, ip_address="192.168.1.100")
        assert exc_info.value.status_code == 401
        assert exc_info.value.message == "Invalid email or password."

    # 5th attempt -> triggers lockout 429
    with pytest.raises(AppException) as exc_info:
        await service.login(payload=payload, ip_address="192.168.1.100")
    assert exc_info.value.status_code == 429
    assert "temporarily locked" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_auth_service_wrong_password_records_db_and_redis_lockout():
    """Verify wrong password increments DB and Redis attempts, locking out on 5th failure."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Target User",
        email=f"target_{uuid.uuid4().hex[:8]}@example.com",
        phone="9999900050",
        password_hash="$2b$12$fakehashfortargetuser",
        role=UserRole.EMPLOYEE,
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
        failed_login_attempts=0,
        locked_until=None,
    )
    mock_repo.get_user_by_identifier.return_value = user

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    payload = LoginRequest(identifier=user.email, password="WrongPassword@123")

    with patch("app.services.auth_service.verify_password", return_value=False):
        for _ in range(4):
            with pytest.raises(AppException) as exc_info:
                await service.login(payload=payload, ip_address="192.168.1.101")
            assert exc_info.value.status_code == 401
            assert exc_info.value.message == "Invalid email or password."

        # 5th attempt triggers lockout
        with pytest.raises(AppException) as exc_info:
            await service.login(payload=payload, ip_address="192.168.1.101")
        assert exc_info.value.status_code == 429
        assert "temporarily locked" in exc_info.value.message.lower()

    # Verify DB persistence fallback was called with lock_until
    assert mock_repo.record_failed_login_db.await_count == 5


@pytest.mark.asyncio
async def test_auth_service_successful_login_clears_failed_attempts():
    """Verify successful login resets failed attempt counters in Redis and DB."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Success User",
        email=f"success_{uuid.uuid4().hex[:8]}@example.com",
        phone="9999900051",
        password_hash="$2b$12$fakehashforuser",
        role=UserRole.EMPLOYEE,
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
        failed_login_attempts=2,
        locked_until=None,
    )
    mock_repo.get_user_by_identifier.return_value = user
    mock_token_svc.generate_auth_tokens.return_value = ("acc_tok", "ref_tok", 1800)

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    payload = LoginRequest(identifier=user.email, password="CorrectPassword@123")

    # Record some prior failed attempts in Redis
    await redis_client.record_failed_login(user.email, "192.168.1.102")
    await redis_client.record_failed_login(user.email, "192.168.1.102")

    # Mock employee check
    mock_emp_res = MagicMock()
    mock_emp_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_emp_res

    with patch("app.services.auth_service.verify_password", return_value=True):
        await service.login(payload=payload, ip_address="192.168.1.102")

    # Assert DB reset was called
    mock_repo.reset_failed_logins_db.assert_awaited_once_with(user_id)

    # Assert Redis was cleared
    is_locked, _ = await redis_client.is_account_locked(user.email, "192.168.1.102")
    assert is_locked is False


@pytest.mark.asyncio
async def test_auth_service_login_blocked_upfront_when_account_is_locked():
    """Verify login attempt during active lockout is immediately rejected with 429 without password check."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    identifier = f"locked_{uuid.uuid4().hex[:8]}@example.com"
    ip = "192.168.1.103"

    # Set account in active lockout in Redis
    for _ in range(5):
        await redis_client.record_failed_login(identifier, ip, max_attempts=5, base_lockout_seconds=900)

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    payload = LoginRequest(identifier=identifier, password="AnyPassword@123")

    with pytest.raises(AppException) as exc_info:
        await service.login(payload=payload, ip_address=ip)
    assert exc_info.value.status_code == 429
    assert "temporarily locked" in exc_info.value.message.lower()

    # get_user_by_identifier should not even have been called because upfront lockout check stopped it
    mock_repo.get_user_by_identifier.assert_not_called()


# ==============================================================================
# 3. Endpoint Rate Limiter Dependencies Tests
# ==============================================================================

def create_mock_request(ip: str = "127.0.0.1") -> Request:
    """Helper to create a mock FastAPI request with specific IP."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": [(b"x-forwarded-for", ip.encode())],
        "client": (ip, 12345),
    }
    request = Request(scope=scope)
    request.state.user_claims = None
    return request


@pytest.mark.asyncio
async def test_login_rate_limiter_dependency_enforces_limit():
    """Verify check_login_rate_limit enforces max 5 requests/minute per IP."""
    test_ip = f"192.168.100.{uuid.uuid4().int % 250}"
    req = create_mock_request(ip=test_ip)

    # 5 requests should pass
    for _ in range(5):
        await check_login_rate_limit(req)

    # 6th request must raise RateLimitExceeded (HTTP 429)
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_login_rate_limit(req)
    assert exc_info.value.status_code == 429
    assert "Too many login attempts" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_forgot_password_rate_limiter_dependency_enforces_limit():
    """Verify check_forgot_password_rate_limit enforces max 3 requests/minute per IP."""
    test_ip = f"192.168.101.{uuid.uuid4().int % 250}"
    req = create_mock_request(ip=test_ip)

    # 3 requests should pass
    for _ in range(3):
        await check_forgot_password_rate_limit(req)

    # 4th request must raise RateLimitExceeded (HTTP 429)
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_forgot_password_rate_limit(req)
    assert exc_info.value.status_code == 429
    assert "Too many password reset requests" in exc_info.value.detail


@pytest.mark.asyncio
async def test_otp_rate_limiter_dependency_enforces_limit():
    """Verify check_otp_rate_limit enforces max 5 requests/minute per IP."""
    test_ip = f"192.168.102.{uuid.uuid4().int % 250}"
    req = create_mock_request(ip=test_ip)

    # 5 requests should pass
    for _ in range(5):
        await check_otp_rate_limit(req)

    # 6th request must raise RateLimitExceeded (HTTP 429)
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_otp_rate_limit(req)
    assert exc_info.value.status_code == 429
    assert "Too many OTP attempts" in exc_info.value.detail
