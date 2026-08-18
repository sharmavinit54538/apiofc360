"""Comprehensive CORS preflight tests for OFC360 FastAPI backend.

Tests verify that:
- OPTIONS preflight requests return HTTP 200 with correct CORS headers
- Production origin (https://www.ofc360.com) is accepted
- Dev origins are accepted in local/dev environment
- Disallowed origins do NOT get CORS headers
- allow_credentials=True does not use wildcard origin
- All affected API paths respond correctly to preflight
- Actual requests from allowed origins include CORS headers
"""

import asyncio
import sys
import os

import pytest
import httpx
from httpx import ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import create_app


PRODUCTION_ORIGIN = "https://www.ofc360.com"
PRODUCTION_ORIGIN_BARE = "https://ofc360.com"
API_ORIGIN = "https://api.ofc360.com"
DEV_ORIGIN = "http://localhost:8080"
DEV_ORIGIN_VITE = "http://localhost:5173"
DISALLOWED_ORIGIN = "https://evil-attacker.com"

# All affected API endpoints from the issue report
AFFECTED_ENDPOINTS = [
    "/api/v1/auth/me",
    "/api/v1/hr-admin/onboarding/status",
    "/api/v1/connect/notifications",
    "/api/v1/attendance/face/analytics",
    "/api/v1/attendance/face/company",
    "/api/v1/attendance/face/me",
    "/api/v1/calendar/holidays",
    "/api/v1/employees",
    "/api/v1/leaves/history",
    "/api/v1/ai/attendance/overtime",
    "/api/v1/ai/attendance/dashboard",
    "/api/v1/timesheets/history",
]

# Additional endpoints to ensure broad coverage
ADDITIONAL_ENDPOINTS = [
    "/api/v1/auth/login",
    "/api/v1/departments",
    "/api/v1/announcements",
    "/api/v1/jobs",
    "/api/v1/assets",
    "/api/v1/exits",
    "/api/v1/documents",
    "/api/v1/payroll/summary",
    "/health",
    "/",
]


@pytest.fixture(scope="module")
def app():
    """Create the FastAPI application."""
    return create_app()


@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for the test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
async def client(app):
    """Create an async HTTP client for testing."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _preflight_headers(origin: str, method: str = "GET", headers: str = "authorization,content-type"):
    """Build standard CORS preflight request headers."""
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": headers,
    }


# ── Test: Production origin OPTIONS preflight ────────────────────────────────

class TestProductionOriginPreflight:
    """Verify OPTIONS preflight works for the production origin across all affected endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_preflight_returns_200(self, client, endpoint):
        """OPTIONS request with production origin must return 200."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        assert response.status_code == 200, (
            f"OPTIONS {endpoint} returned {response.status_code}, expected 200. "
            f"Headers: {dict(response.headers)}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_has_allow_origin_header(self, client, endpoint):
        """OPTIONS response must include Access-Control-Allow-Origin matching production origin."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin == PRODUCTION_ORIGIN, (
            f"OPTIONS {endpoint}: Access-Control-Allow-Origin={allow_origin!r}, "
            f"expected {PRODUCTION_ORIGIN!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_has_allow_credentials(self, client, endpoint):
        """OPTIONS response must include Access-Control-Allow-Credentials: true."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        allow_creds = response.headers.get("access-control-allow-credentials")
        assert allow_creds == "true", (
            f"OPTIONS {endpoint}: Access-Control-Allow-Credentials={allow_creds!r}, expected 'true'"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_has_allow_methods(self, client, endpoint):
        """OPTIONS response must include Access-Control-Allow-Methods."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        allow_methods = response.headers.get("access-control-allow-methods")
        assert allow_methods is not None, (
            f"OPTIONS {endpoint}: Missing Access-Control-Allow-Methods header"
        )
        # Should include the requested method
        assert "GET" in allow_methods.upper(), (
            f"OPTIONS {endpoint}: GET not in Access-Control-Allow-Methods={allow_methods!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_has_allow_headers(self, client, endpoint):
        """OPTIONS response must include Access-Control-Allow-Headers."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        allow_headers = response.headers.get("access-control-allow-headers")
        assert allow_headers is not None, (
            f"OPTIONS {endpoint}: Missing Access-Control-Allow-Headers header"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_no_redirect(self, client, endpoint):
        """OPTIONS request must NOT redirect (3xx)."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
            follow_redirects=False,
        )
        assert response.status_code < 300 or response.status_code >= 400, (
            f"OPTIONS {endpoint} returned redirect {response.status_code}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS)
    async def test_options_not_auth_error(self, client, endpoint):
        """OPTIONS request must NOT return 401/403/405."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        assert response.status_code not in (401, 403, 405, 500), (
            f"OPTIONS {endpoint} returned {response.status_code} — "
            f"authentication/authorization is blocking preflight!"
        )


# ── Test: Multiple HTTP methods in preflight ─────────────────────────────────

class TestPreflightMethods:
    """Verify preflight works for different HTTP methods (POST, PUT, PATCH, DELETE)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def test_preflight_various_methods(self, client, method):
        """Preflight with various Access-Control-Request-Method values should succeed."""
        response = await client.options(
            "/api/v1/employees",
            headers=_preflight_headers(PRODUCTION_ORIGIN, method=method),
        )
        assert response.status_code == 200, (
            f"OPTIONS /api/v1/employees with method={method} returned {response.status_code}"
        )
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN


# ── Test: Alternative production origins ─────────────────────────────────────

class TestAlternativeOrigins:
    """Verify that ofc360.com (without www) and api.ofc360.com also work."""

    @pytest.mark.asyncio
    async def test_bare_domain_origin(self, client):
        """https://ofc360.com should be accepted."""
        response = await client.options(
            "/api/v1/auth/me",
            headers=_preflight_headers(PRODUCTION_ORIGIN_BARE),
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN_BARE

    @pytest.mark.asyncio
    async def test_api_domain_origin(self, client):
        """https://api.ofc360.com should be accepted."""
        response = await client.options(
            "/api/v1/auth/me",
            headers=_preflight_headers(API_ORIGIN),
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == API_ORIGIN


# ── Test: Development origins ────────────────────────────────────────────────

class TestDevOrigins:
    """Verify dev origins work (they are in ALLOWED_ORIGINS and BACKEND_CORS_ORIGINS)."""

    @pytest.mark.asyncio
    async def test_localhost_8080_origin(self, client):
        """http://localhost:8080 should be accepted."""
        response = await client.options(
            "/api/v1/auth/me",
            headers=_preflight_headers(DEV_ORIGIN),
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == DEV_ORIGIN

    @pytest.mark.asyncio
    async def test_localhost_5173_origin(self, client):
        """http://localhost:5173 (Vite) should be accepted."""
        response = await client.options(
            "/api/v1/auth/me",
            headers=_preflight_headers(DEV_ORIGIN_VITE),
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == DEV_ORIGIN_VITE


# ── Test: Disallowed origins ─────────────────────────────────────────────────

class TestDisallowedOrigins:
    """Verify that unknown origins do NOT get CORS headers."""

    @pytest.mark.asyncio
    async def test_disallowed_origin_no_cors(self, client):
        """Unknown origin should NOT get Access-Control-Allow-Origin header."""
        response = await client.options(
            "/api/v1/auth/me",
            headers=_preflight_headers(DISALLOWED_ORIGIN),
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        # CORSMiddleware returns 400 for disallowed origins on preflight, OR
        # returns 200 but without the CORS headers
        assert allow_origin != DISALLOWED_ORIGIN, (
            f"Disallowed origin {DISALLOWED_ORIGIN!r} was accepted — security issue!"
        )
        assert allow_origin != "*", (
            "Wildcard origin returned — not allowed with credentials!"
        )


# ── Test: Credentials + wildcard safety ──────────────────────────────────────

class TestCredentialsSafety:
    """Verify allow_credentials=True does not produce Access-Control-Allow-Origin: *."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", AFFECTED_ENDPOINTS[:3])
    async def test_no_wildcard_with_credentials(self, client, endpoint):
        """When credentials are enabled, origin must be specific — never *."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin != "*", (
            f"OPTIONS {endpoint}: Access-Control-Allow-Origin=* with credentials=true — "
            f"browsers will reject this!"
        )


# ── Test: Actual GET requests include CORS headers ───────────────────────────

class TestActualRequestCors:
    """Verify that actual (non-preflight) requests also include CORS headers."""

    @pytest.mark.asyncio
    async def test_get_health_includes_cors(self, client):
        """GET /health with Origin header should include CORS response headers."""
        response = await client.get(
            "/health",
            headers={"Origin": PRODUCTION_ORIGIN},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN

    @pytest.mark.asyncio
    async def test_get_root_includes_cors(self, client):
        """GET / with Origin header should include CORS response headers."""
        response = await client.get(
            "/",
            headers={"Origin": PRODUCTION_ORIGIN},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN

    @pytest.mark.asyncio
    async def test_cors_debug_endpoint(self, client):
        """GET /api/v1/cors-debug should return CORS configuration info."""
        response = await client.get(
            "/api/v1/cors-debug",
            headers={"Origin": PRODUCTION_ORIGIN},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cors_debug"] is True
        assert PRODUCTION_ORIGIN in data["allowed_origins"]
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN


# ── Test: Additional endpoints ───────────────────────────────────────────────

class TestAdditionalEndpoints:
    """Verify CORS works for additional endpoints beyond the reported affected ones."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ADDITIONAL_ENDPOINTS)
    async def test_additional_endpoint_preflight(self, client, endpoint):
        """OPTIONS preflight should work for all API routes."""
        response = await client.options(
            endpoint,
            headers=_preflight_headers(PRODUCTION_ORIGIN),
        )
        assert response.status_code == 200, (
            f"OPTIONS {endpoint} returned {response.status_code}"
        )
        assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN, (
            f"OPTIONS {endpoint}: Missing or wrong Access-Control-Allow-Origin"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
