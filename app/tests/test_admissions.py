import pytest

from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_admission_workflow(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/admissions", headers=headers, json={"student_name": "New Kid", "class_applying_for": "6", "contact": "9999999999"})
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["status"] == "pending"
    assert r.json()["form_number"].startswith("ADM")

    r = await client.patch(f"/api/v1/admissions/{aid}/status", headers=headers, json={"status": "verified"})
    assert r.status_code == 200
    assert r.json()["status"] == "verified"

    # invalid transition: verified -> pending not allowed
    r_bad = await client.patch(f"/api/v1/admissions/{aid}/status", headers=headers, json={"status": "pending"})
    assert r_bad.status_code == 400

    r2 = await client.patch(f"/api/v1/admissions/{aid}/status", headers=headers, json={"status": "approved"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


async def test_duplicate_admission_application(client, seeded_school):
    token = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"student_name": "Dup Kid", "class_applying_for": "6", "contact": "8888888888"}
    r1 = await client.post("/api/v1/admissions", headers=headers, json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/admissions", headers=headers, json=payload)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "DUPLICATE_APPLICATION"
