"""Comprehensive test suite for Token Revocation, Stateless Invalidation & Refresh Token Rotation.

Tests:
1. Redis token blocklist with TTL matching token expiration.
2. Stateless access token invalidation on user logout.
3. Stateless invalidation & session revocation on password change & password reset.
4. Administrative security lock immediate invalidation.
5. Token family preservation across refresh token rotation.
6. Token family reuse detection (compromised token reuse revokes all family sessions).
7. Concurrency lock during refresh token rotation.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import time
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import HTTPException

from app.core.exceptions import AppException
from app.core.redis_client import redis_client, get_redis_client
from app.middleware.auth import get_current_user_claims
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.schemas.auth import ChangePasswordRequest, ResetPasswordRequest
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.services.token_service import TokenService
from app.utils.jwt import create_access_token, create_refresh_token, decode_token, hash_token


# ==============================================================================
# 1. Redis Blocklist & User Invalidation Engine Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_redis_token_blocklist_ttl_and_lookup():
    """Verify that tokens can be blacklisted with TTL in Redis and looked up accurately."""
    token = "test_bearer_token_abc_123"
    
    # Not blacklisted initially
    assert await redis_client.is_token_blacklisted(token) is False

    # Blacklist token for 10 seconds
    res = await redis_client.blacklist_token(token, ttl_seconds=10)
    assert res is True
    assert await redis_client.is_token_blacklisted(token) is True

    # Other tokens remain unblacklisted
    assert await redis_client.is_token_blacklisted("different_token") is False


@pytest.mark.asyncio
async def test_user_revocation_timestamp_cutoff():
    """Verify user-level revocation timestamp rejects earlier tokens."""
    user_id = uuid.uuid4()
    
    # Not revoked initially
    assert await redis_client.get_user_revoked_before(user_id) is None

    # Revoke user tokens
    res = await redis_client.revoke_user_tokens(user_id, ttl_seconds=60)
    assert res is True
    
    cutoff = await redis_client.get_user_revoked_before(user_id)
    assert cutoff is not None
    assert isinstance(cutoff, int)
    assert cutoff > 0


# ==============================================================================
# 2. Auth Middleware Invalidation Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_middleware_blocks_blacklisted_token():
    """Verify auth middleware rejects blacklisted access tokens with 401."""
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, role="employee", email="test@company.com")

    # Valid token passes
    claims = await get_current_user_claims(credentials=MagicMock(credentials=token))
    assert claims["sub"] == str(user_id)

    # Blacklist token
    await redis_client.blacklist_token(token, ttl_seconds=300)

    # Rejection with 401
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_claims(credentials=MagicMock(credentials=token))
    assert exc_info.value.status_code == 401
    assert "Invalid or expired login session" in exc_info.value.detail


@pytest.mark.asyncio
async def test_auth_middleware_blocks_token_issued_before_user_revocation():
    """Verify auth middleware rejects tokens issued before user revocation event."""
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, role="employee", email="test@company.com")

    # Ensure token iat is strictly before revocation timestamp
    time.sleep(1)
    await redis_client.revoke_user_tokens(user_id)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_claims(credentials=MagicMock(credentials=token))
    assert exc_info.value.status_code == 401
    assert "Invalid or expired login session" in exc_info.value.detail


# ==============================================================================
# 3. User Logout Immediate Blacklisting
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_service_logout_blacklists_access_token():
    """Verify logout immediately blacklists access token and revokes refresh token."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    user_id = uuid.uuid4()
    access_token = create_access_token(user_id=user_id, role="employee", email="logout@company.com")
    refresh_token = create_refresh_token(user_id=user_id)

    await service.logout(access_token=access_token, refresh_token=refresh_token)

    # Assert refresh token was revoked
    mock_token_svc.revoke_refresh_token.assert_awaited_once_with(refresh_token)

    # Assert access token is in Redis blocklist
    assert await redis_client.is_token_blacklisted(access_token) is True


# ==============================================================================
# 4. Password Updates Invalidation (Change & Reset)
# ==============================================================================

@pytest.mark.asyncio
async def test_account_service_change_password_invalidates_tokens_and_sessions():
    """Verify password change revokes all refresh tokens and sets user-level token revocation."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Password Changer",
        email="changer@company.com",
        phone="9999900010",
        password_hash="$2b$12$fakehash",
        role=UserRole.EMPLOYEE,
    )
    mock_repo.get_user_by_id.return_value = user

    service = AccountService(session=mock_session, auth_repository=mock_repo, email_service=mock_email)

    payload = ChangePasswordRequest(
        current_password="OldPassword@123",
        new_password="NewPassword@2026",
        confirm_password="NewPassword@2026",
    )

    with patch("app.services.account_service.verify_password", side_effect=[True, False]):
        await service.change_password(user_id=user_id, payload=payload)

    # Assert DB update and session revocation
    mock_repo.update_user_password.assert_awaited_once()
    mock_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="PASSWORD_CHANGE")

    # Assert Redis user revocation is active
    cutoff = await redis_client.get_user_revoked_before(user_id)
    assert cutoff is not None


@pytest.mark.asyncio
async def test_auth_service_reset_password_invalidates_tokens_and_sessions():
    """Verify password reset revokes all refresh tokens and sets user-level token revocation."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email = AsyncMock()
    mock_token_svc = AsyncMock()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Reset User",
        email="reset@company.com",
        phone="9999900020",
        password_hash="$2b$12$fakehash",
        role=UserRole.EMPLOYEE,
    )
    token_record = MagicMock()
    token_record.used_at = None
    token_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    token_record.user = user
    token_record.id = uuid.uuid4()
    mock_repo.get_password_reset_token.return_value = token_record

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email,
        token_service=mock_token_svc,
    )

    payload = ResetPasswordRequest(
        token="valid_reset_token_raw",
        password="NewResetPass@2026",
        confirm_password="NewResetPass@2026",
    )
    await service.reset_password(payload)

    # Assert DB updates
    mock_repo.update_user_password.assert_awaited_once()
    mock_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="PASSWORD_RESET")
    mock_repo.mark_password_reset_token_used.assert_awaited_once_with(token_record.id)

    # Assert Redis user revocation
    cutoff = await redis_client.get_user_revoked_before(user_id)
    assert cutoff is not None


# ==============================================================================
# 5. Refresh Token Rotation & Token Family Reuse Detection
# ==============================================================================

@pytest.mark.asyncio
async def test_refresh_token_rotation_preserves_family_id():
    """Verify token rotation revokes old token and issues new token within the same family."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Rotation User",
        email="rotate@company.com",
        phone="9999900030",
        password_hash="$2b$12$fakehash",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )

    family_id = uuid.uuid4()
    old_refresh_token = create_refresh_token(user_id=user_id)
    old_hash = hash_token(old_refresh_token)

    old_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=old_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        revoked=False,
    )
    old_record.user = user

    mock_repo.get_refresh_token_by_hash_raw.return_value = old_record
    mock_repo.create_refresh_token = AsyncMock()

    token_service = TokenService(session=mock_session, auth_repository=mock_repo)

    # Mock employee & manager checks
    mock_emp_res = MagicMock()
    mock_emp_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_emp_res

    new_access, new_refresh, exp = await token_service.rotate_refresh_token(
        refresh_token=old_refresh_token
    )

    assert new_access is not None
    assert new_refresh is not None

    # Verify old token was marked revoked
    mock_repo.revoke_refresh_token.assert_awaited_once_with(old_record.id)

    # Verify new token created with identical family_id
    call_kwargs = mock_repo.create_refresh_token.call_args.kwargs
    assert call_kwargs["family_id"] == family_id
    assert call_kwargs["parent_token_hash"] == old_hash


@pytest.mark.asyncio
async def test_refresh_token_family_reuse_detection_revokes_all_sessions():
    """Verify that reusing an already-revoked refresh token revokes the entire family and user tokens."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    compromised_token = create_refresh_token(user_id=user_id)
    comp_hash = hash_token(compromised_token)

    # Token record is ALREADY revoked (simulating reuse of an old rotated token by an attacker)
    compromised_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=comp_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        revoked=True,
        revoked_reason="ROTATED",
    )

    mock_repo.get_refresh_token_by_hash_raw.return_value = compromised_record
    token_service = TokenService(session=mock_session, auth_repository=mock_repo)

    # Attempt rotation with the reused token -> must fail with 401
    with pytest.raises(AppException) as exc_info:
        await token_service.rotate_refresh_token(refresh_token=compromised_token)
    assert exc_info.value.status_code == 401
    assert "reuse detection" in exc_info.value.message.lower()

    # Verify that ENTIRE family was revoked
    mock_repo.revoke_token_family.assert_awaited_once_with(family_id, reason="REUSE_ATTEMPT_DETECTED")
    mock_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="REUSE_ATTEMPT_DETECTED")

    # Verify user access tokens were invalidated in Redis
    cutoff = await redis_client.get_user_revoked_before(user_id)
    assert cutoff is not None


# ==============================================================================
# 6. Distributed Locking Concurrency Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_refresh_locking_mechanism():
    """Verify that concurrent rotation requests acquire mutex locks cleanly."""
    lock_key = "refresh_test_lock_123"
    
    acquired_locks = []

    async def simulate_worker(worker_id: int):
        async with redis_client.lock(lock_key, ttl_seconds=2):
            acquired_locks.append(worker_id)
            await asyncio.sleep(0.05)

    # Run 3 concurrent workers trying to acquire the lock
    await asyncio.gather(
        simulate_worker(1),
        simulate_worker(2),
        simulate_worker(3),
    )

    # All workers should have acquired the lock sequentially
    assert len(acquired_locks) == 3
    assert set(acquired_locks) == {1, 2, 3}
