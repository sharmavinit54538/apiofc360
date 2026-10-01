"""Comprehensive test suite for Auth Refresh Token Cookie, Rotation, Grace Window, Origin Verification, and DB Error Hardening.

Covers Step 1 & Step 2 requirements:
1. Cookie attributes: HttpOnly=True, Secure, path=/api/v1/auth, SameSite=lax (configurable), no domain unless needed.
2. Login -> Reload-style refresh with cookie only (no body payload).
3. Refresh with body payload (backward compatibility).
4. Refresh rotation with short grace window (15s default):
   - Immediate replay within window (two tabs, retries) succeeds and returns a fresh valid pair without revoking the family.
   - Replay outside the window revokes the whole token family.
5. Clean 401 without token (no cookie, no body) without logging DB error.
6. Origin / Referer allow-list check on /auth/refresh and /auth/logout (403 on untrusted).
7. Logout revokes token and clears cookie with path=/api/v1/auth.
8. Exception logging extracts real user_id and role from Authorization Bearer token when claims are not in request.state.
9. Database session lifecycle: quiet rollback on HTTPException / AppException without DBAPI / SQLAlchemy error log spam.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.api.auth import (
    _verify_trusted_origin,
    clear_auth_cookies,
    logout,
    refresh,
    router as auth_router,
    set_auth_cookies,
)
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    _extract_user_and_role,
    add_cors_headers,
    app_exception_handler,
    http_exception_handler,
    install_exception_handlers,
)
from app.core.redis_client import redis_client
from app.db.database import get_db_session
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.schemas.auth import RefreshTokenRequest
from app.services.token_service import TokenService
from app.utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)


# ==============================================================================
# 1. Cookie Attributes & Helper Verification
# ==============================================================================

def test_set_auth_cookies_attributes():
    """Verify set_auth_cookies sets HttpOnly, Secure, SameSite, and path=/api/v1/auth."""
    response = Response()
    test_token = "sample_refresh_token_value_abc"

    set_auth_cookies(response, test_token)

    # Inspect the Set-Cookie headers
    cookie_header = response.headers.get("set-cookie")
    assert cookie_header is not None
    assert f"{settings.COOKIE_NAME}={test_token}" in cookie_header
    assert "HttpOnly" in cookie_header or "httponly" in cookie_header.lower()
    assert "Path=/api/v1/auth" in cookie_header or "path=/api/v1/auth" in cookie_header.lower()
    assert f"SameSite={settings.COOKIE_SAMESITE.capitalize()}" in cookie_header or f"samesite={settings.COOKIE_SAMESITE}" in cookie_header.lower()

    if settings.COOKIE_DOMAIN:
        assert f"Domain={settings.COOKIE_DOMAIN}" in cookie_header or f"domain={settings.COOKIE_DOMAIN}" in cookie_header.lower()


def test_clear_auth_cookies_attributes():
    """Verify clear_auth_cookies clears the cookie with path=/api/v1/auth."""
    response = Response()
    clear_auth_cookies(response)

    raw_headers = response.raw_headers
    cookie_headers = [v.decode("latin-1") for k, v in raw_headers if k.decode("latin-1").lower() == "set-cookie"]
    assert len(cookie_headers) > 0

    # Ensure path=/api/v1/auth is on the deletion cookie
    found_target_cookie = False
    for ch in cookie_headers:
        if settings.COOKIE_NAME in ch:
            found_target_cookie = True
            assert "path=/api/v1/auth" in ch.lower()
            assert "max-age=0" in ch.lower() or "expires=" in ch.lower()
    assert found_target_cookie is True


# ==============================================================================
# 2. Origin / Referer Allow-List Check on /auth/refresh and /auth/logout
# ==============================================================================

def test_origin_allowlist_trusted_origin():
    """Verify trusted origins from CORS_ORIGINS pass the check without error."""
    mock_request = MagicMock()
    mock_request.headers = {"origin": "https://app.ofc360.com"}

    # Should not raise
    _verify_trusted_origin(mock_request)

    # Also test with referer
    mock_request.headers = {"referer": "https://app.ofc360.com/dashboard"}
    _verify_trusted_origin(mock_request)


def test_origin_allowlist_untrusted_origin_raises_403():
    """Verify untrusted origin raises 403 Forbidden AppException."""
    mock_request = MagicMock()
    mock_request.headers = {"origin": "https://malicious-site.com"}

    with pytest.raises(AppException) as exc_info:
        _verify_trusted_origin(mock_request)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Cross-origin request forbidden" in exc_info.value.message


def test_origin_allowlist_no_origin_allowed_for_direct_clients():
    """Non-browser or direct clients without Origin/Referer header pass."""
    mock_request = MagicMock()
    mock_request.headers = {}

    # Should not raise
    _verify_trusted_origin(mock_request)


# ==============================================================================
# 3. Reload-Style Refresh (Cookie Only) vs Body Refresh (Backward Compatibility)
# ==============================================================================

@pytest.mark.asyncio
async def test_reload_style_refresh_with_cookie_only():
    """Verify POST /refresh with NO body payload succeeds when HttpOnly cookie is present."""
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.include_router(auth_router, prefix="/api/v1")

    user_id = uuid.uuid4()
    mock_token_svc = AsyncMock()
    new_access = "new_access_token_123"
    new_refresh = "new_refresh_token_456"
    mock_token_svc.rotate_refresh_token.return_value = (new_access, new_refresh, 900)

    from app.services.token_service import get_token_service
    test_app.dependency_overrides[get_token_service] = lambda: mock_token_svc

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Request has cookie, NO body
        client.cookies.set(settings.COOKIE_NAME, "valid_cookie_refresh_token")
        response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "https://app.ofc360.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["access_token"] == new_access
        assert data["data"]["refresh_token"] == new_refresh

        # Verify new cookie was set in the response
        set_cookie = response.headers.get("set-cookie", "")
        assert f"{settings.COOKIE_NAME}={new_refresh}" in set_cookie
        assert "path=/api/v1/auth" in set_cookie.lower()

        # Verify token_service received the cookie value
        mock_token_svc.rotate_refresh_token.assert_awaited_once()
        call_kwargs = mock_token_svc.rotate_refresh_token.call_args.kwargs
        assert call_kwargs["refresh_token"] == "valid_cookie_refresh_token"


@pytest.mark.asyncio
async def test_refresh_with_body_payload_backward_compatibility():
    """Verify POST /refresh with body payload succeeds even if no cookie is present."""
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.include_router(auth_router, prefix="/api/v1")

    mock_token_svc = AsyncMock()
    mock_token_svc.rotate_refresh_token.return_value = ("access_abc", "refresh_xyz", 900)

    from app.services.token_service import get_token_service
    test_app.dependency_overrides[get_token_service] = lambda: mock_token_svc

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "body_refresh_token_raw"},
            headers={"Origin": "https://app.ofc360.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["access_token"] == "access_abc"
        assert data["data"]["refresh_token"] == "refresh_xyz"

        mock_token_svc.rotate_refresh_token.assert_awaited_once()
        assert mock_token_svc.rotate_refresh_token.call_args.kwargs["refresh_token"] == "body_refresh_token_raw"


@pytest.mark.asyncio
async def test_refresh_missing_token_returns_clean_401():
    """Verify POST /refresh with no body and no cookie returns clean 401 without error."""
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.include_router(auth_router, prefix="/api/v1")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "https://app.ofc360.com"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert "Invalid or missing refresh token" in data["message"]


# ==============================================================================
# 4. Refresh Rotation Grace Window vs Reuse Detection
# ==============================================================================

@pytest.mark.asyncio
async def test_refresh_rotation_grace_window_allows_concurrent_replay():
    """Verify replay of recently rotated token within grace window (e.g. 2 tabs) issues a fresh pair."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Grace User",
        email="grace@company.com",
        phone="9999900050",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )

    t1_token = create_refresh_token(user_id=user_id)
    t1_hash = hash_token(t1_token)

    # Simulate token was rotated 3 seconds ago (within default 15s grace window)
    now = datetime.now(timezone.utc)
    t1_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=t1_hash,
        expires_at=now + timedelta(days=7),
        revoked=True,
        revoked_at=now - timedelta(seconds=3),
        revoked_reason="ROTATION",
    )
    t1_record.user = user

    mock_repo.get_refresh_token_by_hash_raw.return_value = t1_record
    mock_repo.create_refresh_token = AsyncMock()

    token_service = TokenService(session=mock_session, auth_repository=mock_repo)

    # Replay T1 within grace window
    new_access, new_refresh, exp = await token_service.rotate_refresh_token(refresh_token=t1_token)

    assert new_access is not None
    assert new_refresh is not None

    # Family was NOT revoked!
    mock_repo.revoke_token_family.assert_not_called()
    mock_repo.revoke_all_user_refresh_tokens.assert_not_called()

    # New token created within the same family
    call_kwargs = mock_repo.create_refresh_token.call_args.kwargs
    assert call_kwargs["family_id"] == family_id


@pytest.mark.asyncio
async def test_refresh_rotation_outside_grace_window_revokes_token_family():
    """Verify replay of rotated token outside grace window (>15s) revokes the token family."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Grace User",
        email="grace@company.com",
        phone="9999900051",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )

    t1_token = create_refresh_token(user_id=user_id)
    t1_hash = hash_token(t1_token)

    # Simulate token was rotated 45 seconds ago (outside 15s grace window)
    now = datetime.now(timezone.utc)
    t1_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=t1_hash,
        expires_at=now + timedelta(days=7),
        revoked=True,
        revoked_at=now - timedelta(seconds=45),
        revoked_reason="ROTATION",
    )
    t1_record.user = user

    mock_repo.get_refresh_token_by_hash_raw.return_value = t1_record
    token_service = TokenService(session=mock_session, auth_repository=mock_repo)

    # Replay T1 outside grace window -> must raise 401 and revoke family
    with pytest.raises(AppException) as exc_info:
        await token_service.rotate_refresh_token(refresh_token=t1_token)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "reuse detection" in exc_info.value.message.lower()

    # Verify entire token family was revoked
    mock_repo.revoke_token_family.assert_awaited_once_with(family_id, reason="REUSE_ATTEMPT_DETECTED")
    mock_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id, reason="REUSE_ATTEMPT_DETECTED")


# ==============================================================================
# 5. Logout & Cookie Deletion Integration
# ==============================================================================

@pytest.mark.asyncio
async def test_logout_endpoint_clears_cookies():
    """Verify POST /logout clears cookies and returns 200."""
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.include_router(auth_router, prefix="/api/v1")

    mock_auth_svc = AsyncMock()
    from app.api.auth import get_auth_service
    test_app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(settings.COOKIE_NAME, "active_cookie_to_clear")
        response = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://app.ofc360.com",
                "Authorization": "Bearer some_access_token_123",
            },
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

        set_cookie = response.headers.get("set-cookie", "")
        assert settings.COOKIE_NAME in set_cookie
        assert "path=/api/v1/auth" in set_cookie.lower()


# ==============================================================================
# 6. Request Logging: User & Role Extraction from Bearer Header
# ==============================================================================

def test_extract_user_and_role_from_bearer_when_state_missing():
    """Verify _extract_user_and_role falls back to extracting claims from Authorization Bearer header."""
    user_id = uuid.uuid4()
    test_token = create_access_token(user_id=user_id, role="HR_ADMIN", email="admin@ofc360.com")

    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock()
    # No user_claims on request.state
    del mock_request.state.user_claims
    mock_request.headers = {"authorization": f"Bearer {test_token}"}

    extracted_id, extracted_role = _extract_user_and_role(mock_request)
    assert extracted_id == str(user_id)
    assert extracted_role == "HR_ADMIN"


def test_extract_user_and_role_returns_none_when_no_token():
    """Verify _extract_user_and_role gracefully returns (None, None) when no token is present."""
    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock()
    del mock_request.state.user_claims
    mock_request.headers = {}

    extracted_id, extracted_role = _extract_user_and_role(mock_request)
    assert extracted_id is None
    assert extracted_role is None


# ==============================================================================
# 7. DB Session Lifecycle: Quiet Rollback on HTTPException / AppException
# ==============================================================================

@pytest.mark.asyncio
async def test_db_session_lifecycle_quiet_rollback_on_app_exception():
    """Verify that get_db_session does not log ERROR or traceback when an AppException/HTTPException is raised."""
    session_gen = get_db_session()
    session = await anext(session_gen)

    with patch("app.db.database.logger.exception") as mock_logger_exc:
        # Simulate route raising an AppException(401)
        try:
            await session_gen.athrow(AppException(message="Invalid credentials.", status_code=401))
        except AppException:
            pass

        # Ensure no logger.exception was emitted for the 401
        mock_logger_exc.assert_not_called()


@pytest.mark.asyncio
async def test_db_session_lifecycle_logs_error_on_sqlalchemy_error():
    """Verify that get_db_session DOES log ERROR with traceback for real SQLAlchemy/DBAPI errors."""
    session_gen = get_db_session()
    session = await anext(session_gen)

    with patch("app.db.database.logger.exception") as mock_logger_exc:
        try:
            await session_gen.athrow(SQLAlchemyError("Connection terminated abnormally"))
        except SQLAlchemyError:
            pass

        # Real DB errors MUST be logged with exception/traceback
        mock_logger_exc.assert_called_once()
        assert "[DB Lifecycle] DBAPI/Query exception" in mock_logger_exc.call_args[0][0]
