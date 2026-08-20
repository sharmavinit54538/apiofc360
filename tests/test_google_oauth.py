import pytest
import uuid
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport, Response

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.company import Company
from app.core.security import hash_password
from app.core.config import settings


@pytest.mark.asyncio
async def test_google_auth_url_endpoint():
    """Verify that GET /api/v1/auth/google/url generates correct authorization URL."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/auth/google/url")
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert "https://accounts.google.com/o/oauth2/v2/auth" in data["url"]
        assert f"client_id={settings.GOOGLE_CLIENT_ID}" in data["url"]
        assert "scope=" in data["url"]

        # With custom redirect_uri
        resp_cb = await client.get("/api/v1/auth/google/url?redirect_uri=https://ofc360.com/auth/google/callback")
        assert resp_cb.status_code == 200
        data_cb = resp_cb.json()
        assert "redirect_uri=" in data_cb["url"]


@pytest.mark.asyncio
async def test_google_auth_login_suite():
    """Verify Google OAuth login endpoint with various scenarios:
    1. 404 when user is not in database.
    2. Successful login with direct email or mock OAuth exchange.
    3. Mock ID token credential verification.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    # 1. Setup real test user and company in DB
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        test_company = Company(
            id=comp_id,
            name=f"Google Test Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
            onboarding_step=7,
        )
        session.add(test_company)

        user_id = uuid.uuid4()
        test_email = f"google_user_{user_id.hex[:8]}@example.com"
        test_user = User(
            id=user_id,
            company_id=comp_id,
            name="Google Test User",
            email=test_email,
            phone=f"97{user_id.int % 100000000:08d}",
            password_hash=hash_password("SecretPass123!"),
            role=UserRole.HR_ADMIN,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
            onboarding_completed=True,
            onboarding_step=7,
        )
        session.add(test_user)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Test 1: Non-existent user returns 404
            non_existent_resp = await client.post(
                "/api/v1/auth/google",
                json={"email": "non_existent_google_9988@example.com"}
            )
            assert non_existent_resp.status_code == 404
            assert non_existent_resp.json()["success"] is False

            # Test 2: Existing user login via direct email fallback
            direct_resp = await client.post(
                "/api/v1/auth/google",
                json={"email": test_email, "name": "Google Test User"}
            )
            assert direct_resp.status_code == 200
            direct_data = direct_resp.json()
            assert direct_data["success"] is True
            assert direct_data["message"] == "Google login successful."
            assert direct_data["data"]["user"]["email"] == test_email
            assert direct_data["data"]["access_token"] is not None
            assert direct_data["data"]["refresh_token"] is not None

            # Test 3: OAuth code exchange flow (mocked Google API)
            orig_post = AsyncClient.post
            orig_get = AsyncClient.get

            async def mock_post(self, url, *args, **kwargs):
                if "oauth2.googleapis.com/token" in str(url):
                    return Response(200, json={"id_token": "mock_google_id_token_12345", "access_token": "mock_access_token"})
                return await orig_post(self, url, *args, **kwargs)

            async def mock_get(self, url, *args, **kwargs):
                if "oauth2.googleapis.com/tokeninfo" in str(url):
                    return Response(200, json={
                        "email": test_email,
                        "name": "Google Test User",
                        "email_verified": "true",
                    })
                return await orig_get(self, url, *args, **kwargs)

            with patch.object(AsyncClient, "post", mock_post), \
                 patch.object(AsyncClient, "get", mock_get):

                code_resp = await client.post(
                    "/api/v1/auth/google",
                    json={"code": "valid_google_auth_code_123"}
                )
                assert code_resp.status_code == 200
                code_data = code_resp.json()
                assert code_data["success"] is True
                assert code_data["data"]["user"]["email"] == test_email

            # Test 4: OAuth code exchange failure (invalid code)
            async def mock_post_err(self, url, *args, **kwargs):
                if "oauth2.googleapis.com/token" in str(url):
                    return Response(200, json={"error": "invalid_grant", "error_description": "Bad Request"})
                return await orig_post(self, url, *args, **kwargs)

            with patch.object(AsyncClient, "post", mock_post_err):
                err_resp = await client.post(
                    "/api/v1/auth/google",
                    json={"code": "invalid_code"}
                )
                assert err_resp.status_code == 400
                assert "Google authentication error" in err_resp.json()["message"]

    finally:
        # Cleanup test data
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()
