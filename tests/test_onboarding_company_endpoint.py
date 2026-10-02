"""Tests for POST /api/v1/onboarding/company endpoint.

Verifies:
1. Exact payload with base64 logo succeeds with 200.
2. company.timezone == "Asia/Kolkata" and company.currency == "USD".
3. Logo is stored as a file path / URL, not as raw base64 in company_profile.
4. Invalid base64 or unsupported image types return 422.
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
from app.models.user import User


@pytest.fixture
def unique_suffix():
    return uuid.uuid4().hex[:8]


async def register_and_login_admin(client: AsyncClient, suffix: str):
    """Helper to create and authenticate a verified HR Admin user."""
    rand_phone = f"98{secrets.randbelow(90000000) + 10000000}"
    letters = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6)).capitalize()
    admin_data = {
        "name": f"Admin Alpha {letters}",
        "email": f"hr_admin_{suffix}@example.com",
        "phone": rand_phone,
        "password": "SecurePassword@123",
        "company_name": f"Initial Company {suffix}",
    }

    reg_resp = await client.post("/api/v1/auth/register", json=admin_data)
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == admin_data["email"]))).scalar_one()
        user.is_verified = True
        user.is_active = True
        user.account_status = "ACTIVE"
        await db.commit()
        company_id = user.company_id

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_data["email"], "password": admin_data["password"]},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token_data = login_resp.json()
    token = token_data.get("access_token") or (token_data.get("data") or {}).get("access_token")
    return admin_data, token, company_id


@pytest.mark.asyncio
async def test_onboarding_company_exact_payload_success(unique_suffix):
    """Test POST /api/v1/onboarding/company with exact prompt payload."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, token, company_id = await register_and_login_admin(client, unique_suffix)
        headers = {"Authorization": f"Bearer {token}"}

        # Valid 1x1 JPEG base64 Data URL
        valid_jpeg_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

        payload = {
            "company_name": "Ecoygam",
            "industry": "Software",
            "company_size": "1–10",
            "country": "India",
            "state": "32",
            "city": "Jaipur",
            "currency": "USD",
            "timezone": "Asia/Kolkata",
            "company_logo": valid_jpeg_b64,
        }

        response = await client.post("/api/v1/onboarding/company", json=payload, headers=headers)
        assert response.status_code == 200, f"POST /api/v1/onboarding/company failed: {response.text}"

        res_json = response.json()
        assert res_json["success"] is True
        data = res_json["data"]
        assert data["timezone"] == "Asia/Kolkata"
        assert data["currency"] == "USD"
        assert data["company_name"] == "Ecoygam"
        assert data["company_logo_url"] is not None
        assert not data["company_logo_url"].startswith("data:image")
        assert data["company_logo_url"].startswith("/uploads/onboarding/company_logo/")

        # Verify DB persistence directly
        async with AsyncSessionLocal() as db:
            company = await db.get(Company, company_id)
            assert company is not None
            assert company.timezone == "Asia/Kolkata"
            assert company.currency == "USD"
            assert company.name == "Ecoygam"
            assert company.company_profile is not None
            logo_url_in_profile = company.company_profile.get("company_logo_url")
            assert logo_url_in_profile is not None
            assert not logo_url_in_profile.startswith("data:")
            assert logo_url_in_profile.startswith("/uploads/onboarding/company_logo/")


@pytest.mark.asyncio
async def test_onboarding_company_invalid_image_returns_422(unique_suffix):
    """Test that invalid base64 image or corrupted data returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, token, _ = await register_and_login_admin(client, unique_suffix)
        headers = {"Authorization": f"Bearer {token}"}

        # Corrupted / invalid image signature
        corrupted_payload = {
            "company_name": "Ecoygam Corrupted",
            "currency": "USD",
            "timezone": "Asia/Kolkata",
            "company_logo": "data:image/jpeg;base64,bm90YW5pbWFnZQ==",
        }

        resp = await client.post("/api/v1/onboarding/company", json=corrupted_payload, headers=headers)
        assert resp.status_code == 422
        assert "Corrupted JPEG" in resp.text or "Invalid image" in resp.text
