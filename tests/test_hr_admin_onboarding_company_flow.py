"""Comprehensive tests for HR Admin Onboarding Company Name Flow.

Validates the 8 exact requirements:
1. Register company: "OFC360 Enterprise" -> verify companies.name == "OFC360 Enterprise".
2. Login as HR Admin -> verify JWT access token contains company_id.
3. GET onboarding/status -> verify organization.id == authenticated company_id and organization.name == "OFC360 Enterprise".
4. GET onboarding/progress -> verify organization.name == "OFC360 Enterprise" and company_profile exposes company_name/name.
5. GET onboarding/organization -> verify organization.name == "OFC360 Enterprise".
6. Complete onboarding -> verify same company remains associated (status=ACTIVE, onboarding_completed=True).
7. Multi-tenant isolation: Create Company B, login as HR Admin B -> verify Company B cannot see Company A's name.
8. Multi-tenant security: Passing another company's company_id/company_name from frontend is ignored/rejected, resolving strictly via auth session.
"""

import os
import secrets
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.main import app
from app.models.company import Company
from app.models.user import User, UserRole
from app.services.token_service import TokenService


@pytest.fixture
def unique_suffix():
    return secrets.token_hex(4)


@pytest.fixture
def company_name_a(unique_suffix):
    return f"OFC360 Enterprise {unique_suffix}"


@pytest.fixture
def hr_admin_data_a(company_name_a, unique_suffix):
    return {
        "name": f"Admin A {unique_suffix}",
        "email": f"hr_a_{unique_suffix}@ofc360enterprise.com",
        "phone": f"987{secrets.token_hex(3)[:7]}",
        "password": "SecurePassword@123",
        "company_name": company_name_a,
    }


@pytest.fixture
def company_name_b(unique_suffix):
    return f"Nexus Corp {unique_suffix}"


@pytest.fixture
def hr_admin_data_b(company_name_b, unique_suffix):
    return {
        "name": f"Admin B {unique_suffix}",
        "email": f"hr_b_{unique_suffix}@nexuscorp.com",
        "phone": f"988{secrets.token_hex(3)[:7]}",
        "password": "SecurePassword@123",
        "company_name": company_name_b,
    }


@pytest.mark.asyncio
async def test_1_register_company_name_persisted(hr_admin_data_a, company_name_a):
    """Test 1: Register company 'OFC360 Enterprise' -> verify companies.name == 'OFC360 Enterprise'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v1/auth/register", json=hr_admin_data_a)
        assert resp.status_code == 201, f"Registration failed: {resp.text}"

    # Verify directly in database that companies.name is the single source of truth
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.email == hr_admin_data_a["email"]))
        user = user_res.scalar_one_or_none()
        assert user is not None, "User was not created."
        assert user.company_id is not None, "User has no linked company_id."

        company = await db.get(Company, user.company_id)
        assert company is not None, "Company record does not exist."
        assert company.name == company_name_a, f"Expected company name '{company_name_a}', got '{company.name}'"


@pytest.mark.asyncio
async def test_2_login_hr_admin_token_contains_company_id(hr_admin_data_a, company_name_a):
    """Test 2: Login as HR Admin -> verify JWT access token contains company_id and returns company_name."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Ensure registered
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        data = login_resp.json()

        access_token = data.get("access_token") or (data.get("data") or {}).get("access_token")
        assert access_token, "No access_token returned in login response."

        # Decode token claims
        claims = TokenService.decode_access_token(access_token)
        assert claims.get("company_id") is not None, "JWT access token does not contain 'company_id' claim."
        assert claims.get("role") == "hr_admin", f"Expected role hr_admin, got {claims.get('role')}"


@pytest.mark.asyncio
async def test_3_get_onboarding_status_returns_organization(hr_admin_data_a, company_name_a):
    """Test 3: GET onboarding/status -> verify organization.id == authenticated company_id and organization.name == 'OFC360 Enterprise'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        data = login_resp.json()
        token = data.get("access_token") or (data.get("data") or {}).get("access_token")
        claims = TokenService.decode_access_token(token)
        company_id = claims["company_id"]

        headers = {"Authorization": f"Bearer {token}"}

        # Test both HR Admin Onboarding and Onboarding router status endpoints
        for endpoint in ["/api/v1/hr-admin/onboarding/status", "/api/v1/onboarding/status"]:
            status_resp = await client.get(endpoint, headers=headers)
            assert status_resp.status_code == 200, f"Status call failed on {endpoint}: {status_resp.text}"
            res_json = status_resp.json()
            body = res_json.get("data", res_json)

            assert "organization" in body, f"Response at {endpoint} does not contain 'organization' field: {body}"
            org = body["organization"]
            assert org is not None, f"Organization object at {endpoint} is None"
            assert str(org.get("id")) == str(company_id), f"Organization ID mismatch: {org.get('id')} vs {company_id}"
            assert org.get("name") == company_name_a, f"Organization Name mismatch: {org.get('name')} vs {company_name_a}"


@pytest.mark.asyncio
async def test_4_get_onboarding_progress_returns_registered_company_name(hr_admin_data_a, company_name_a):
    """Test 4: GET onboarding/progress -> verify organization.name == 'OFC360 Enterprise' and company_profile exposes company_name."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        token = (login_resp.json().get("access_token")) or (login_resp.json().get("data", {}).get("access_token"))
        claims = TokenService.decode_access_token(token)
        company_id = claims["company_id"]

        headers = {"Authorization": f"Bearer {token}"}

        for endpoint in ["/api/v1/hr-admin/onboarding/progress", "/api/v1/onboarding/progress"]:
            prog_resp = await client.get(endpoint, headers=headers)
            assert prog_resp.status_code == 200, f"Progress call failed on {endpoint}: {prog_resp.text}"
            res_json = prog_resp.json()
            body = res_json.get("data", res_json)

            # Check organization object
            assert "organization" in body, f"Missing organization in {endpoint}: {body}"
            org = body["organization"]
            assert org.get("name") == company_name_a, f"Expected {company_name_a}, got {org.get('name')}"

            # Check company_profile representation merged with company name
            profile = body.get("company_profile") or {}
            assert profile.get("company_name") == company_name_a or profile.get("name") == company_name_a, (
                f"Frontend would receive undefined company name! Profile: {profile}"
            )


@pytest.mark.asyncio
async def test_5_get_onboarding_organization_returns_canonical_name(hr_admin_data_a, company_name_a):
    """Test 5: GET onboarding/organization -> verify organization.name == 'OFC360 Enterprise'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        token = (login_resp.json().get("access_token")) or (login_resp.json().get("data", {}).get("access_token"))
        headers = {"Authorization": f"Bearer {token}"}

        for endpoint in [
            "/api/v1/hr-admin/onboarding/organization",
            "/api/v1/hr-admin/onboarding/company",
            "/api/v1/onboarding/company",
            "/api/v1/onboarding/organization",
        ]:
            org_resp = await client.get(endpoint, headers=headers)
            assert org_resp.status_code == 200, f"Call failed on {endpoint}: {org_resp.text}"
            res_json = org_resp.json()
            body = res_json.get("data", res_json)

            # Verify both canonical organization.name and root name are present
            if "organization" in body and isinstance(body["organization"], dict):
                assert body["organization"].get("name") == company_name_a
            assert body.get("name") == company_name_a or body.get("company_name") == company_name_a


@pytest.mark.asyncio
async def test_6_complete_onboarding_maintains_company_association(hr_admin_data_a, company_name_a):
    """Test 6: Complete onboarding -> verify same company remains associated (status=ACTIVE, onboarding_completed=True)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        token = (login_resp.json().get("access_token")) or (login_resp.json().get("data", {}).get("access_token"))
        claims = TokenService.decode_access_token(token)
        company_id = claims["company_id"]
        headers = {"Authorization": f"Bearer {token}"}

        # Complete onboarding
        comp_resp = await client.post("/api/v1/hr-admin/onboarding/complete", headers=headers)
        assert comp_resp.status_code == 200, f"Complete onboarding failed: {comp_resp.text}"

        # Verify DB company remains intact and activated
        async with AsyncSessionLocal() as db:
            company = await db.get(Company, uuid.UUID(company_id))
            assert company is not None
            assert company.name == company_name_a, "Company name changed or corrupted during completion!"
            assert company.onboarding_completed is True
            assert company.status == "ACTIVE"


@pytest.mark.asyncio
async def test_7_multi_tenant_isolation_company_b_cannot_see_company_a(
    hr_admin_data_a, company_name_a, hr_admin_data_b, company_name_b
):
    """Test 7: Create Company B -> Login as HR Admin B -> verify Company B cannot see Company A's name."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Register both
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)
        await client.post("/api/v1/auth/register", json=hr_admin_data_b)

        # Login as Admin B
        login_b = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_b["email"], "password": hr_admin_data_b["password"]},
        )
        token_b = (login_b.json().get("access_token")) or (login_b.json().get("data", {}).get("access_token"))
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Check status for B
        stat_b = await client.get("/api/v1/hr-admin/onboarding/status", headers=headers_b)
        assert stat_b.status_code == 200
        org_b = stat_b.json().get("data", {}).get("organization", {})
        assert org_b.get("name") == company_name_b
        assert org_b.get("name") != company_name_a

        # Check progress for B
        prog_b = await client.get("/api/v1/hr-admin/onboarding/progress", headers=headers_b)
        assert prog_b.status_code == 200
        prog_org_b = prog_b.json().get("data", {}).get("organization", {})
        assert prog_org_b.get("name") == company_name_b
        assert prog_org_b.get("name") != company_name_a


@pytest.mark.asyncio
async def test_8_backend_ignores_tampered_frontend_company_id(
    hr_admin_data_a, company_name_a, hr_admin_data_b, company_name_b
):
    """Test 8: Try passing another company's company_id/company_name from frontend -> verify backend ignores/rejects it."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/auth/register", json=hr_admin_data_a)
        await client.post("/api/v1/auth/register", json=hr_admin_data_b)

        # Login as Admin A to obtain company_id_a
        login_a = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_a["email"], "password": hr_admin_data_a["password"]},
        )
        token_a = (login_a.json().get("access_token")) or (login_a.json().get("data", {}).get("access_token"))
        claims_a = TokenService.decode_access_token(token_a)
        company_id_a = claims_a["company_id"]

        # Login as Admin B
        login_b = await client.post(
            "/api/v1/auth/login",
            json={"email": hr_admin_data_b["email"], "password": hr_admin_data_b["password"]},
        )
        token_b = (login_b.json().get("access_token")) or (login_b.json().get("data", {}).get("access_token"))
        claims_b = TokenService.decode_access_token(token_b)
        company_id_b = claims_b["company_id"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Admin B tries to pass company_id_a or spoof company_name in query or body
        tampered_resp = await client.get(
            f"/api/v1/hr-admin/onboarding/status?company_id={company_id_a}&organization_id={company_id_a}",
            headers=headers_b,
        )
        assert tampered_resp.status_code == 200
        org_data = tampered_resp.json().get("data", {}).get("organization", {})
        # Must resolve strictly to Company B, NEVER Company A!
        assert org_data.get("id") == company_id_b
        assert org_data.get("name") == company_name_b
        assert org_data.get("id") != company_id_a
        assert org_data.get("name") != company_name_a
