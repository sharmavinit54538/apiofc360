import pytest

from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _create_student(client, headers):
    r = await client.post("/api/v1/students", headers=headers, json={"admission_number": "AT1", "first_name": "Test", "class_name": "10", "section": "A"})
    return r.json()["id"]


async def test_bulk_mark_and_report(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _create_student(client, headers)

    r = await client.post("/api/v1/attendance", headers=headers, json={
        "date": "2026-08-10", "class_name": "10", "section": "A",
        "records": [{"student_id": sid, "status": "present"}],
    })
    assert r.status_code == 201
    assert r.json()["created"] == 1

    r2 = await client.get("/api/v1/attendance/report", headers=headers, params={"start_date": "2026-08-01", "end_date": "2026-08-31"})
    assert r2.status_code == 200
    rows = r2.json()
    assert rows[0]["present"] == 1
    assert rows[0]["attendance_rate"] == 100.0


async def test_duplicate_attendance_updates_not_duplicates(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _create_student(client, headers)

    body = {"date": "2026-08-10", "class_name": "10", "section": "A", "records": [{"student_id": sid, "status": "present"}]}
    r1 = await client.post("/api/v1/attendance", headers=headers, json=body)
    assert r1.json()["created"] == 1

    body["records"][0]["status"] = "absent"
    r2 = await client.post("/api/v1/attendance", headers=headers, json=body)
    assert r2.json()["updated"] == 1
    assert r2.json()["created"] == 0

    r3 = await client.get("/api/v1/attendance", headers=headers, params={"date": "2026-08-10"})
    assert len(r3.json()) == 1
    assert r3.json()[0]["status"] == "absent"


async def test_export_csv(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _create_student(client, headers)
    await client.post("/api/v1/attendance", headers=headers, json={"date": "2026-08-10", "class_name": "10", "section": "A", "records": [{"student_id": sid, "status": "present"}]})

    r = await client.get("/api/v1/attendance/export/csv", headers=headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


async def test_student_role_cannot_mark_attendance(client, db_sessionmaker, seeded_school):
    from app.core.security import hash_password
    from app.models.user import User

    async with db_sessionmaker() as db:
        db.add(User(tenant_id=seeded_school["school_id"], school_id=seeded_school["school_id"], name="Stu", email="stu@test.com", role="student", password_hash=hash_password("Password@123"), status="active"))
        await db.commit()

    token = await login(client, seeded_school["school_code"], "stu@test.com")
    r = await client.post("/api/v1/attendance", headers={"Authorization": f"Bearer {token}"}, json={"date": "2026-08-10", "class_name": "10", "records": []})
    assert r.status_code == 403
