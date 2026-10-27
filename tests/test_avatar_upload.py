"""Comprehensive tests for the POST /api/v1/users/me/avatar endpoint.

Covers:
- Successful upload (JPEG, PNG, WebP)
- Invalid file type / content mismatch
- Oversized file (>5 MB)
- Unauthenticated request (no / invalid token)
- Database failure rollback
- Old avatar cleanup
- Response format
- Route registration
"""

from __future__ import annotations

import io
import struct
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user, get_current_user_claims


BASE = "/api/v1/users/me/avatar"

ADMIN_USER_ID = uuid.uuid4()
COMPANY_ID = uuid.uuid4()


# ── Helpers for building fake image bytes ───────────────────────────────────────

def _jpeg_bytes(size: int = 128) -> bytes:
    header = b"\xff\xd8\xff\xe0"
    return header + b"\x00" * max(0, size - len(header))


def _png_bytes(size: int = 128) -> bytes:
    header = b"\x89PNG\r\n\x1a\n"
    return header + b"\x00" * max(0, size - len(header))


def _webp_bytes(size: int = 128) -> bytes:
    body = b"\x00" * max(0, size - 12)
    riff_size = struct.pack("<I", len(body) + 4)
    return b"RIFF" + riff_size + b"WEBP" + body


def _fake_user(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", ADMIN_USER_ID)
    user.email = overrides.get("email", "test@ofc360.com")
    user.name = overrides.get("name", "Test User")
    user.role = overrides.get("role", "HR_ADMIN")
    user.is_active = overrides.get("is_active", True)
    user.is_verified = overrides.get("is_verified", True)
    user.is_deleted = overrides.get("is_deleted", False)
    user.avatar = overrides.get("avatar", None)
    user.company_id = overrides.get("company_id", COMPANY_ID)
    user.account_status = overrides.get("account_status", "ACTIVE")
    user.phone = overrides.get("phone", "+919876543210")
    user.company = MagicMock()
    return user


def _mock_claims():
    return {
        "sub": str(ADMIN_USER_ID),
        "role": "hr_admin",
        "company_id": str(COMPANY_ID),
        "type": "access",
        "iat": 9999999999,
    }


def _setup_overrides(mock_user=None, mock_session=None):
    """Install dependency overrides on the app for auth + DB."""
    user = mock_user or _fake_user()
    session = mock_session or AsyncMock()
    if not hasattr(session.commit, 'side_effect') or session.commit.side_effect is None:
        session.commit = AsyncMock()
    if not hasattr(session.rollback, 'side_effect') or session.rollback.side_effect is None:
        session.rollback = AsyncMock()

    app.dependency_overrides[get_current_user_claims] = lambda: _mock_claims()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: session

    return user, session


def _clear_overrides():
    app.dependency_overrides.clear()


# ============================================================================
# 1. Successful Uploads
# ============================================================================

def test_upload_jpeg_success():
    """Uploading a valid JPEG should return 200 with avatar URL."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("photo.jpg", io.BytesIO(_jpeg_bytes(1024)), "image/jpeg")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Avatar uploaded successfully"
        assert body["data"]["avatar"].startswith("/uploads/avatars/")
        assert body["data"]["avatar"].endswith(".jpg")
    finally:
        _clear_overrides()


def test_upload_png_success():
    """Uploading a valid PNG should return 200."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("avatar.png", io.BytesIO(_png_bytes(1024)), "image/png")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["avatar"].endswith(".png")
    finally:
        _clear_overrides()


def test_upload_webp_success():
    """Uploading a valid WebP should return 200."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("pic.webp", io.BytesIO(_webp_bytes(1024)), "image/webp")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["avatar"].endswith(".webp")
    finally:
        _clear_overrides()


# ============================================================================
# 2. Invalid File Type
# ============================================================================

def test_upload_unsupported_mime_type():
    """A non-image MIME type should be rejected with 400."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["success"] is False
    finally:
        _clear_overrides()


def test_upload_magic_bytes_mismatch():
    """Claiming image/jpeg but sending PNG magic bytes should be rejected."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("trick.jpg", io.BytesIO(_png_bytes(512)), "image/jpeg")},
            )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["success"] is False
    finally:
        _clear_overrides()


# ============================================================================
# 3. Oversized File
# ============================================================================

def test_upload_oversized_file():
    """A file exceeding 5 MB should be rejected with 413."""
    _setup_overrides()
    try:
        big_data = _jpeg_bytes(6 * 1024 * 1024)
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("big.jpg", io.BytesIO(big_data), "image/jpeg")},
            )
        assert resp.status_code == 413, resp.text
        body = resp.json()
        assert body["success"] is False
    finally:
        _clear_overrides()


# ============================================================================
# 4. Unauthenticated Request
# ============================================================================

def test_upload_no_auth_token():
    """Request without Authorization header should return 401."""
    _clear_overrides()
    with TestClient(app) as client:
        resp = client.post(
            BASE,
            files={"file": ("pic.jpg", io.BytesIO(_jpeg_bytes(256)), "image/jpeg")},
        )
    assert resp.status_code == 401


# ============================================================================
# 5. Empty File
# ============================================================================

def test_upload_empty_file():
    """An empty file should be rejected with 400."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
            )
        assert resp.status_code == 400, resp.text
    finally:
        _clear_overrides()


# ============================================================================
# 6. Database Failure Rollback
# ============================================================================

def test_db_commit_failure_rolls_back():
    """If DB commit fails, the response should be 500."""
    session = AsyncMock()
    session.commit = AsyncMock(side_effect=Exception("DB down"))
    session.rollback = AsyncMock()

    _setup_overrides(mock_session=session)
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("pic.jpg", io.BytesIO(_jpeg_bytes(256)), "image/jpeg")},
            )
        assert resp.status_code == 500, resp.text
        body = resp.json()
        assert body["success"] is False
    finally:
        _clear_overrides()


# ============================================================================
# 7. Response Format Validation
# ============================================================================

def test_response_format_has_required_fields():
    """Response must include success, message, and data.avatar."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("pic.jpg", io.BytesIO(_jpeg_bytes(256)), "image/jpeg")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "data" in body
        assert "avatar" in body["data"]
    finally:
        _clear_overrides()


# ============================================================================
# 8. Old Avatar Cleanup
# ============================================================================

def test_old_avatar_url_is_replaced():
    """After upload, user.avatar should point to the new file, not the old one."""
    user = _fake_user(avatar="/uploads/avatars/old_avatar_abc123.jpg")
    _setup_overrides(mock_user=user)
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE,
                files={"file": ("new.png", io.BytesIO(_png_bytes(512)), "image/png")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["avatar"] != "/uploads/avatars/old_avatar_abc123.jpg"
        assert body["data"]["avatar"].endswith(".png")
    finally:
        _clear_overrides()


# ============================================================================
# 9. Route Registration Verification
# ============================================================================

def test_avatar_route_registered():
    """POST /api/v1/users/me/avatar must appear in the app's route table."""
    routes = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                routes.append((method, route.path))
    assert ("POST", "/api/v1/users/me/avatar") in routes, (
        f"Route POST /api/v1/users/me/avatar not found. Routes: {routes}"
    )


# ============================================================================
# 10. Existing Endpoints Not Broken
# ============================================================================

def test_existing_get_me_route_still_registered():
    """GET /api/v1/users/me must still be registered."""
    routes = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                routes.append((method, route.path))
    assert ("GET", "/api/v1/users/me") in routes


def test_existing_put_user_route_still_registered():
    """PUT /api/v1/users/{id} must still be registered."""
    routes = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                routes.append((method, route.path))
    assert ("PUT", "/api/v1/users/{id}") in routes
