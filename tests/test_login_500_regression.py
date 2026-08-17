"""Regression test for production login HTTP 500 (GitHub issue: JWT algorithm mismatch).

Root cause: jwt.py unconditionally loaded RSA PEM keys even when JWT_ALGORITHM
was HS256 and no RSA keys were configured, causing:
    ValueError: Unable to load PEM file. MalformedFraming

This test verifies the login endpoint never returns 500 for any standard
authentication scenario.
"""

import os
import sys

if not os.environ.get("DATABASE_URL") or "7y1812xhKIHW" in os.environ.get("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:Bindu%40134366@localhost:5432/equnixsphere_prod"

import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import create_app
from app.db.database import AsyncSessionLocal, engine
from app.models.user import User, UserRole
from app.models.company import Company
from app.core.security import hash_password







@pytest.mark.asyncio
async def test_login_valid_credentials_returns_200_not_500():
    """Valid login must return 200 with access_token and refresh_token (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    test_email = f"regtest_{user_id.hex[:8]}@example.com"
    raw_password = "Regression@Test123"

    # Seed test data
    async with AsyncSessionLocal() as session:
        session.add(Company(id=comp_id, name=f"RegTest Corp {comp_id.hex[:6]}"))
        session.add(User(
            id=user_id,
            company_id=comp_id,
            name="Regression Tester",
            email=test_email,
            phone=f"70{user_id.int % 100000000:08d}",
            password_hash=hash_password(raw_password),
            role=UserRole.HR_ADMIN,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        ))
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": test_email, "password": raw_password},
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()
            assert data["success"] is True
            assert "access_token" in data["data"]
            assert "refresh_token" in data["data"]
            assert data["data"]["user"]["email"] == test_email
            assert data["data"]["user"]["role"] == "hr_admin"
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401_not_500():
    """Wrong password must return 401 (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    test_email = f"regtest_wp_{user_id.hex[:8]}@example.com"

    async with AsyncSessionLocal() as session:
        session.add(Company(id=comp_id, name=f"RegTest WP Corp {comp_id.hex[:6]}"))
        session.add(User(
            id=user_id,
            company_id=comp_id,
            name="WP Tester",
            email=test_email,
            phone=f"71{user_id.int % 100000000:08d}",
            password_hash=hash_password("CorrectPassword@123"),
            role=UserRole.HR_ADMIN,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        ))
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": test_email, "password": "WrongPassword@999"},
            )
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
            assert resp.json()["success"] is False
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401_not_500():
    """Unknown email must return 401 (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "nonexistent_regtest_xyz@example.com", "password": "Password@123"},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
        assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_login_missing_fields_returns_422():
    """Missing required fields must return 422 (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Missing password
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "test@example.com"},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

        # Empty body
        resp2 = await client.post(
            "/api/v1/auth/login",
            json={},
        )
        assert resp2.status_code == 422, f"Expected 422, got {resp2.status_code}: {resp2.text}"


@pytest.mark.asyncio
async def test_login_suspended_user_returns_403_not_500():
    """Suspended user must return 403 (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    test_email = f"regtest_susp_{user_id.hex[:8]}@example.com"
    raw_password = "Suspended@Test123"

    async with AsyncSessionLocal() as session:
        session.add(Company(id=comp_id, name=f"RegTest Susp Corp {comp_id.hex[:6]}"))
        session.add(User(
            id=user_id,
            company_id=comp_id,
            name="Suspended Tester",
            email=test_email,
            phone=f"72{user_id.int % 100000000:08d}",
            password_hash=hash_password(raw_password),
            role=UserRole.EMPLOYEE,
            account_status="SUSPENDED",
            is_active=False,
            is_verified=True,
        ))
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": test_email, "password": raw_password},
            )
            assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
            assert resp.json()["success"] is False
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_login_each_role_returns_200():
    """Valid users with each supported role must login successfully (not 500)."""
    app = create_app()
    transport = ASGITransport(app=app)

    roles_to_test = [UserRole.HR_ADMIN, UserRole.EMPLOYEE, UserRole.MANAGER, UserRole.CTO]
    created_ids = []

    for role in roles_to_test:
        comp_id = uuid.uuid4()
        user_id = uuid.uuid4()
        test_email = f"regtest_{role.value}_{user_id.hex[:6]}@example.com"
        raw_password = "RoleTest@Pwd123"

        async with AsyncSessionLocal() as session:
            session.add(Company(id=comp_id, name=f"RegTest {role.value} Corp"))
            session.add(User(
                id=user_id,
                company_id=comp_id,
                name=f"{role.value.title()} Tester",
                email=test_email,
                phone=f"73{user_id.int % 100000000:08d}",
                password_hash=hash_password(raw_password),
                role=role,
                account_status="ACTIVE",
                is_active=True,
                is_verified=True,
            ))
            await session.commit()
        created_ids.append((user_id, comp_id))

        try:
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.post(
                    "/api/v1/auth/login",
                    json={"identifier": test_email, "password": raw_password},
                )
                assert resp.status_code == 200, (
                    f"Role {role.value}: Expected 200, got {resp.status_code}: {resp.text}"
                )
                data = resp.json()
                assert data["success"] is True
                assert data["data"]["user"]["role"] == role.value
        finally:
            pass  # cleanup below

    # Cleanup all test data
    for user_id, comp_id in created_ids:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()
