import pytest

from app.tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_tenant_a_cannot_read_tenant_b_student(client, seeded_school, second_school):
    token_a = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    token_b = await login(client, second_school["school_code"], second_school["admin_email"])

    r = await client.post("/api/v1/students", headers={"Authorization": f"Bearer {token_b}"},
                           json={"admission_number": "B001", "first_name": "Ben", "class_name": "9"})
    assert r.status_code == 201
    b_student_id = r.json()["id"]

    r2 = await client.get(f"/api/v1/students/{b_student_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r2.status_code == 404  # not leaked as 200, not distinguishable from "doesn't exist"


async def test_tenant_a_list_never_contains_tenant_b_students(client, seeded_school, second_school):
    token_a = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    token_b = await login(client, second_school["school_code"], second_school["admin_email"])

    await client.post("/api/v1/students", headers={"Authorization": f"Bearer {token_a}"}, json={"admission_number": "A001", "first_name": "Aya", "class_name": "9"})
    await client.post("/api/v1/students", headers={"Authorization": f"Bearer {token_b}"}, json={"admission_number": "B001", "first_name": "Ben", "class_name": "9"})

    r = await client.get("/api/v1/students", headers={"Authorization": f"Bearer {token_a}"})
    names = [s["first_name"] for s in r.json()["items"]]
    assert "Aya" in names
    assert "Ben" not in names


async def test_forged_tenant_header_is_rejected(client, seeded_school, second_school):
    token_a = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    # attempt to impersonate tenant B by sending its id in the header —
    # the header must never override the JWT's own tenant claim.
    r = await client.get("/api/v1/students", headers={"Authorization": f"Bearer {token_a}", "X-Tenant-ID": second_school["school_id"]})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "TENANT_MISMATCH"


async def test_cross_tenant_fee_access_blocked(client, seeded_school, second_school):
    token_a = await login(client, seeded_school["school_code"], seeded_school["admin_email"])
    token_b = await login(client, second_school["school_code"], second_school["admin_email"])

    r = await client.post("/api/v1/students", headers={"Authorization": f"Bearer {token_b}"}, json={"admission_number": "B001", "first_name": "Ben", "class_name": "9"})
    student_id = r.json()["id"]
    r2 = await client.post("/api/v1/fees", headers={"Authorization": f"Bearer {token_b}"}, json={"student_id": student_id, "academic_year": "2026", "fee_type": "tuition", "amount": "1000.00"})
    assert r2.status_code == 201
    fee_id = r2.json()["id"]

    r3 = await client.get(f"/api/v1/fees/{fee_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r3.status_code == 404
