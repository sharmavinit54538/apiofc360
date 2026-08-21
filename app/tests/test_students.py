import pytest

from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_create_list_get_update_delete_student(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/students", headers=headers, json={"admission_number": "S001", "first_name": "Asha", "class_name": "8", "section": "B"})
    assert r.status_code == 201
    sid = r.json()["id"]

    r = await client.get("/api/v1/students", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await client.get(f"/api/v1/students/{sid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["first_name"] == "Asha"

    r = await client.put(f"/api/v1/students/{sid}", headers=headers, json={"section": "C"})
    assert r.status_code == 200
    assert r.json()["section"] == "C"

    r = await client.delete(f"/api/v1/students/{sid}", headers=headers)
    assert r.status_code == 204

    r = await client.get(f"/api/v1/students/{sid}", headers=headers)
    assert r.json()["status"] == "inactive"  # soft delete, not gone


async def test_duplicate_admission_number_rejected(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"admission_number": "DUP1", "first_name": "First", "class_name": "8"}
    r1 = await client.post("/api/v1/students", headers=headers, json=payload)
    assert r1.status_code == 201
    payload2 = {**payload, "first_name": "Second"}
    r2 = await client.post("/api/v1/students", headers=headers, json=payload2)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "DUPLICATE_ADMISSION_NUMBER"
