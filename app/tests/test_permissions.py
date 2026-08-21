import pytest

from app.core.security import hash_password
from app.models.user import User
from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _make_user(db_sessionmaker, tenant_id, role, email):
    async with db_sessionmaker() as db:
        db.add(User(tenant_id=tenant_id, school_id=tenant_id, name=role, email=email, role=role, password_hash=hash_password("Password@123"), status="active"))
        await db.commit()


async def test_teacher_cannot_create_student(client, db_sessionmaker, seeded_school):
    await _make_user(db_sessionmaker, seeded_school["school_id"], "teacher", "t@test.com")
    token = await login(client, seeded_school["school_code"], "t@test.com")
    r = await client.post("/api/v1/students", headers={"Authorization": f"Bearer {token}"}, json={"admission_number": "X1", "first_name": "X", "class_name": "9"})
    assert r.status_code == 403


async def test_teacher_can_read_students(client, db_sessionmaker, seeded_school):
    await _make_user(db_sessionmaker, seeded_school["school_id"], "teacher", "t2@test.com")
    token = await login(client, seeded_school["school_code"], "t2@test.com")
    r = await client.get("/api/v1/students", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_accountant_cannot_manage_users(client, db_sessionmaker, seeded_school):
    await _make_user(db_sessionmaker, seeded_school["school_id"], "accountant", "acc@test.com")
    token = await login(client, seeded_school["school_code"], "acc@test.com")
    r = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_accountant_can_manage_fees(client, db_sessionmaker, seeded_school):
    await _make_user(db_sessionmaker, seeded_school["school_id"], "accountant", "acc2@test.com")
    token = await login(client, seeded_school["school_code"], "acc2@test.com")
    r = await client.get("/api/v1/fees", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_malformed_jwt_rejected(client):
    r = await client.get("/api/v1/students", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


async def test_admin_cannot_change_own_role(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    my_id = r.json()["id"]
    r2 = await client.put(f"/api/v1/users/{my_id}", headers={"Authorization": f"Bearer {token}"}, json={"role": "teacher"})
    assert r2.status_code == 400
