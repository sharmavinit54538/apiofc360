import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from sqlalchemy import select

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.company import Company
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_auth_login_comprehensive_suite():
    """Verify auth login route behavior:
    1. Returns 401 (not 500) for non-existent users.
    2. Returns 401 (not 500) for wrong password.
    3. Successfully logs in valid active verified users without any 500 or relationship errors.
    4. Handles company lazy loading and onboarding sync cleanly.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Test 1: Non-existent user
        non_existent_resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "nonexistent_random_user_12345@example.com", "password": "Password@123"}
        )
        assert non_existent_resp.status_code == 401
        res_json = non_existent_resp.json()
        assert res_json["success"] is False

        # Test 2: Create a real test company and user in DB
        async with AsyncSessionLocal() as session:
            comp_id = uuid.uuid4()
            test_company = Company(
                id=comp_id,
                name=f"Login Test Corp {comp_id.hex[:6]}",
                onboarding_completed=True,
                onboarding_step=7,
            )
            session.add(test_company)

            user_id = uuid.uuid4()
            test_email = f"test_login_{user_id.hex[:8]}@example.com"
            raw_password = "SecurePassword@123"
            test_user = User(
                id=user_id,
                company_id=comp_id,
                name="Login Tester",
                email=test_email,
                phone=f"99{user_id.int % 100000000:08d}",
                password_hash=hash_password(raw_password),
                role=UserRole.SUPER_ADMIN,
                account_status="ACTIVE",
                is_active=True,
                is_verified=True,
                onboarding_completed=False,
                onboarding_step=1,
            )
            session.add(test_user)
            await session.commit()

        try:
            # Test 3: Wrong password returns 401 (not 500)
            wrong_pw_resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": test_email, "password": "WrongPassword@999"}
            )
            assert wrong_pw_resp.status_code == 401
            assert wrong_pw_resp.json()["success"] is False

            # Test 4: Correct credentials returns 200 with tokens and user details
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": test_email, "password": raw_password}
            )
            assert login_resp.status_code == 200
            login_data = login_resp.json()
            assert login_data["success"] is True
            assert "access_token" in login_data["data"]
            assert "refresh_token" in login_data["data"]
            assert login_data["data"]["user"]["email"] == test_email
            assert login_data["data"]["user"]["role"] == "super_admin"
            assert login_data["data"]["user"]["company_name"] is not None

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
