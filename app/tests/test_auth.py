import pytest

from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_valid_login(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    assert token

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == seeded_school["admin_email"]


async def test_invalid_password(client, seeded_school):
    r = await client.post("/api/v1/auth/login", json={"school_code": seeded_school["school_code"], "email": seeded_school["admin_email"], "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_invalid_school_code(client, seeded_school):
    r = await client.post("/api/v1/auth/login", json={"school_code": "NOPE", "email": seeded_school["admin_email"], "password": "Password@123"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SCHOOL_NOT_FOUND"


async def test_no_token_rejected(client):
    r = await client.get("/api/v1/students")
    assert r.status_code == 401


async def test_refresh_rotation(client, seeded_school):
    r = await client.post("/api/v1/auth/login", json={"school_code": seeded_school["school_code"], "email": seeded_school["admin_email"], "password": "Password@123"})
    old_refresh = r.json()["refresh_token"]

    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 200
    new_access = r2.json()["access_token"]
    assert new_access != r.json()["access_token"]

    # old refresh token must now be revoked (rotation)
    r3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r3.status_code == 401


async def test_inactive_user_login_blocked(client, db_sessionmaker, seeded_school):
    from sqlalchemy import select
    from app.models.user import User

    async with db_sessionmaker() as db:
        user = (await db.execute(select(User).where(User.email == seeded_school["admin_email"]))).scalar_one()
        user.status = "inactive"
        await db.commit()

    r = await client.post("/api/v1/auth/login", json={"school_code": seeded_school["school_code"], "email": seeded_school["admin_email"], "password": "Password@123"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "USER_INACTIVE"


async def test_suspended_school_blocks_login(client, db_sessionmaker, seeded_school):
    from app.models.school import School

    async with db_sessionmaker() as db:
        school = await db.get(School, seeded_school["school_id"])
        school.status = "suspended"
        await db.commit()

    r = await client.post("/api/v1/auth/login", json={"school_code": seeded_school["school_code"], "email": seeded_school["admin_email"], "password": "Password@123"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "SCHOOL_SUSPENDED"
