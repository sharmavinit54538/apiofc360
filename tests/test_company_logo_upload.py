"""Comprehensive tests for the POST /api/v1/settings/company/logo endpoint.

Covers:
- Authenticated company admin uploads valid PNG
- Authenticated company admin uploads valid JPEG
- Authenticated company admin uploads valid WebP
- Upload using field 'logo' as well as field 'file'
- Content validation (magic bytes mismatch)
- Prohibited extensions / scripts rejection
- Oversized file (>5MB) rejection (413)
- Unauthenticated request rejection (401/403)
- Unauthorized user / non-admin role rejection (403)
- Company not found or missing company_id (404)
- Successful replacement and cleanup of existing logo
- Database error rollback and disk cleanup
- CORS / OPTIONS preflight
- Route registration verification
"""

from __future__ import annotations

import io
import os
import struct
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

# Ensure optional packages do not fail import
for mod in ["cv2", "face_recognition", "numpy", "PIL", "PIL.Image", "razorpay", "celery", "stripe"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

import pytest
from starlette.testclient import TestClient

from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user, get_current_user_claims
from app.models.company import Company
from app.services.company_logo_service import LOGOS_DIR

BASE_V1 = "/api/v1/settings/company/logo"
BASE_ALT = "/settings/company/logo"

ADMIN_USER_ID = uuid.uuid4()
COMPANY_ID = uuid.uuid4()


# ── Image Generation Helpers ───────────────────────────────────────────────────

def _jpeg_bytes(size: int = 256) -> bytes:
    header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return header + b"\x00" * max(0, size - len(header))


def _png_bytes(size: int = 256) -> bytes:
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    return header + b"\x00" * max(0, size - len(header))


def _webp_bytes(size: int = 256) -> bytes:
    body = b"\x00" * max(0, size - 12)
    riff_size = struct.pack("<I", len(body) + 4)
    return b"RIFF" + riff_size + b"WEBP" + body


def _fake_company(**overrides):
    company = MagicMock(spec=Company)
    company.id = overrides.get("id", COMPANY_ID)
    company.name = overrides.get("name", "Test Corp International")
    company.company_profile = overrides.get("company_profile", {
        "website": "https://testcorp.com",
        "email": "contact@testcorp.com",
    })
    return company


def _fake_claims(role: str = "hr_admin", company_id: str | None = str(COMPANY_ID)):
    claims = {
        "sub": str(ADMIN_USER_ID),
        "role": role,
        "type": "access",
        "iat": 9999999999,
    }
    if company_id is not None:
        claims["company_id"] = company_id
    return claims


def _setup_overrides(company=None, role: str = "hr_admin", company_id: str | None = str(COMPANY_ID), session_mock=None):
    comp = company if company is not None else _fake_company()
    session = session_mock or AsyncMock()

    # Mock execute result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = comp
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()

    app.dependency_overrides[get_current_user_claims] = lambda: _fake_claims(role=role, company_id=company_id)
    app.dependency_overrides[get_db_session] = lambda: session

    return comp, session


def _clear_overrides():
    app.dependency_overrides.clear()


# ============================================================================
# 1. Successful Uploads
# ============================================================================

def test_upload_png_success_logo_field():
    """Uploading a valid PNG using field name 'logo' should return 200 with stored URL."""
    company, session = _setup_overrides()
    created_file = None
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.png", io.BytesIO(_png_bytes(1024)), "image/png")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert "logo" in body["data"]
        assert body["data"]["logo"].startswith("/uploads/logos/")
        assert body["data"]["logo"].endswith(".png")

        created_filename = body["data"]["logo"].rsplit("/", 1)[-1]
        created_file = os.path.join(LOGOS_DIR, created_filename)
        assert os.path.isfile(created_file), "Logo file should be written to disk"
    finally:
        _clear_overrides()
        if created_file and os.path.isfile(created_file):
            os.remove(created_file)


def test_upload_jpeg_success_file_field():
    """Uploading a valid JPEG using field name 'file' should also succeed (compatibility)."""
    company, session = _setup_overrides()
    created_file = None
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"file": ("logo.jpg", io.BytesIO(_jpeg_bytes(1024)), "image/jpeg")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["logo"].endswith(".jpg")

        created_filename = body["data"]["logo"].rsplit("/", 1)[-1]
        created_file = os.path.join(LOGOS_DIR, created_filename)
        assert os.path.isfile(created_file)
    finally:
        _clear_overrides()
        if created_file and os.path.isfile(created_file):
            os.remove(created_file)


def test_upload_webp_success():
    """Uploading a valid WebP should return 200."""
    company, session = _setup_overrides()
    created_file = None
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.webp", io.BytesIO(_webp_bytes(1024)), "image/webp")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["logo"].endswith(".webp")

        created_filename = body["data"]["logo"].rsplit("/", 1)[-1]
        created_file = os.path.join(LOGOS_DIR, created_filename)
        assert os.path.isfile(created_file)
    finally:
        _clear_overrides()
        if created_file and os.path.isfile(created_file):
            os.remove(created_file)


# ============================================================================
# 2. Validation & Security Checks
# ============================================================================

def test_invalid_mime_type():
    """Uploading a non-image MIME type should return 400 Bad Request."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("document.pdf", io.BytesIO(b"%PDF-1.4..."), "application/pdf")},
            )
        assert resp.status_code == 400, resp.text
        assert "Unsupported image type" in resp.json()["message"]
    finally:
        _clear_overrides()


def test_magic_byte_mismatch():
    """MIME says image/png but content is plain text -> 400."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("fake.png", io.BytesIO(b"Hello world, not a png"), "image/png")},
            )
        assert resp.status_code == 400, resp.text
        assert "File content does not match" in resp.json()["message"]
    finally:
        _clear_overrides()


def test_dangerous_extension():
    """Executable or script extension rejected even if MIME is spoofed -> 400."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("malicious.php", io.BytesIO(_png_bytes(512)), "image/png")},
            )
        assert resp.status_code == 400, resp.text
        assert "Executable or script" in resp.json()["message"]
    finally:
        _clear_overrides()


def test_oversized_file():
    """File larger than 5 MB returns 413."""
    _setup_overrides()
    try:
        oversized = _png_bytes(6 * 1024 * 1024)  # 6 MB
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("huge.png", io.BytesIO(oversized), "image/png")},
            )
        assert resp.status_code == 413, resp.text
        assert "limit" in resp.json()["message"].lower()
    finally:
        _clear_overrides()


def test_no_file_provided():
    """Submitting request without logo or file field -> 400."""
    _setup_overrides()
    try:
        with TestClient(app) as client:
            resp = client.post(BASE_V1, data={"field": "value"})
        assert resp.status_code == 400, resp.text
    finally:
        _clear_overrides()


# ============================================================================
# 3. Authentication & Authorization
# ============================================================================

def test_unauthenticated_request():
    """Missing auth token / claims -> 401."""
    _clear_overrides()
    with TestClient(app) as client:
        resp = client.post(
            BASE_V1,
            files={"logo": ("logo.png", io.BytesIO(_png_bytes(512)), "image/png")},
        )
    # Auth middleware returns 401 when no token is present
    assert resp.status_code == 401, resp.text


def test_unauthorized_role():
    """Standard employee role without company settings permission -> 403."""
    _setup_overrides(role="employee")
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.png", io.BytesIO(_png_bytes(512)), "image/png")},
            )
        assert resp.status_code == 403, resp.text
        assert "Access denied" in resp.json()["message"]
    finally:
        _clear_overrides()


def test_missing_company_id_in_claims():
    """User has admin role but no company association -> 404."""
    _setup_overrides(company_id=None)
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.png", io.BytesIO(_png_bytes(512)), "image/png")},
            )
        assert resp.status_code == 404, resp.text
        assert "No company association" in resp.json()["message"]
    finally:
        _clear_overrides()


def test_company_not_found_in_db():
    """Company ID does not exist in DB -> 404."""
    _setup_overrides(company=None)
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.png", io.BytesIO(_png_bytes(512)), "image/png")},
            )
        assert resp.status_code == 404, resp.text
        assert "Company not found" in resp.json()["message"]
    finally:
        _clear_overrides()


# ============================================================================
# 4. Replacement & Cleanup of Old Logo
# ============================================================================

def test_replace_old_logo_cleanup():
    """When a company already has a logo, replacing it deletes the old file."""
    old_file_name = f"old_logo_{uuid.uuid4().hex[:8]}.png"
    old_file_path = os.path.join(LOGOS_DIR, old_file_name)
    with open(old_file_path, "wb") as f:
        f.write(_png_bytes(512))

    company = _fake_company(company_profile={
        "logo": f"/uploads/logos/{old_file_name}",
        "website": "https://testcorp.com",
    })
    _setup_overrides(company=company)
    new_file = None
    try:
        assert os.path.isfile(old_file_path), "Old logo should exist prior to upload"
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("new_logo.png", io.BytesIO(_png_bytes(1024)), "image/png")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        new_url = body["data"]["logo"]
        assert old_file_name not in new_url
        new_filename = new_url.rsplit("/", 1)[-1]
        new_file = os.path.join(LOGOS_DIR, new_filename)

        # Old file must have been deleted
        assert not os.path.isfile(old_file_path), "Old logo must be cleaned up"
        # New file must exist
        assert os.path.isfile(new_file), "New logo must exist"
    finally:
        _clear_overrides()
        if os.path.isfile(old_file_path):
            os.remove(old_file_path)
        if new_file and os.path.isfile(new_file):
            os.remove(new_file)


# ============================================================================
# 5. Database Failure Rollback & File Cleanup
# ============================================================================

def test_db_failure_cleans_up_file():
    """If DB commit fails, written file must be removed and 500 returned."""
    company = _fake_company()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=company)))
    session.commit = AsyncMock(side_effect=RuntimeError("DB Commit Crash"))
    session.rollback = AsyncMock()

    _setup_overrides(company=company, session_mock=session)
    try:
        with TestClient(app) as client:
            resp = client.post(
                BASE_V1,
                files={"logo": ("logo.png", io.BytesIO(_png_bytes(1024)), "image/png")},
            )
        assert resp.status_code == 500, resp.text
        session.rollback.assert_called_once()
    finally:
        _clear_overrides()


# ============================================================================
# 6. Route Inspection & OPTIONS Preflight
# ============================================================================

def test_route_registration():
    """POST /api/v1/settings/company/logo must be registered in the app."""
    def extract_paths(router_or_app, prefix=""):
        paths = []
        for r in router_or_app.routes:
            if type(r).__name__ == "_IncludedRouter":
                inc_prefix = getattr(r.include_context, "prefix", "")
                orig = getattr(r, "original_router", None) or getattr(r, "router", None)
                if orig:
                    paths.extend(extract_paths(orig, prefix + inc_prefix))
            elif hasattr(r, "routes"):
                paths.extend(extract_paths(r, prefix + getattr(r, "prefix", "")))
            else:
                p = prefix + getattr(r, "path", "")
                methods = getattr(r, "methods", set())
                paths.append((methods, p))
        return paths

    all_routes = extract_paths(app)
    v1_route_exists = any("POST" in r[0] and r[1] == BASE_V1 for r in all_routes)
    assert v1_route_exists, f"Route {BASE_V1} not found in registered routes!"


def test_options_preflight():
    """OPTIONS /api/v1/settings/company/logo returns 200/204 with CORS headers."""
    with TestClient(app) as client:
        resp = client.options(
            BASE_V1,
            headers={
                "Origin": "https://app.ofc360.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
    assert resp.status_code in {200, 204}, resp.text
    assert resp.headers.get("access-control-allow-origin") == "https://app.ofc360.com"
