import asyncio
import sys
import os
import uuid
from fastapi.testclient import TestClient

sys.path.insert(0, os.getcwd())

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.user import User
from app.models.company import Company
from app.core.security import create_access_token
from sqlalchemy import select

def test_cors_and_put():
    app = create_app()
    client = TestClient(app)
    origin = "http://192.168.31.235:8080"
    target_id = "e7f1f422-2dab-40a1-8101-16102b9c2e65"

    print("==================================================")
    print("TEST 1: OPTIONS Preflight /api/v1/employees")
    print("==================================================")
    res_opt1 = client.options(
        "/api/v1/employees",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
    )
    print(f"Status Code: {res_opt1.status_code}")
    print(f"Access-Control-Allow-Origin: {res_opt1.headers.get('access-control-allow-origin')}")
    print(f"Access-Control-Allow-Credentials: {res_opt1.headers.get('access-control-allow-credentials')}")
    assert res_opt1.status_code == 200
    assert res_opt1.headers.get("access-control-allow-origin") == origin
    assert res_opt1.headers.get("access-control-allow-credentials") == "true"

    print("\n==================================================")
    print("TEST 2: OPTIONS Preflight /api/v1/employees/{target_id}")
    print("==================================================")
    res_opt2 = client.options(
        f"/api/v1/employees/{target_id}",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
    )
    print(f"Status Code: {res_opt2.status_code}")
    print(f"Access-Control-Allow-Origin: {res_opt2.headers.get('access-control-allow-origin')}")
    print(f"Access-Control-Allow-Credentials: {res_opt2.headers.get('access-control-allow-credentials')}")
    assert res_opt2.status_code == 200
    assert res_opt2.headers.get("access-control-allow-origin") == origin
    assert res_opt2.headers.get("access-control-allow-credentials") == "true"

    # Setup token for authenticated API requests
    async def get_test_token():
        async with AsyncSessionLocal() as session:
            comp_res = await session.execute(select(Company))
            comp = comp_res.scalars().first()
            user_res = await session.execute(select(User).where(User.company_id == comp.id))
            admin_user = user_res.scalars().first()
            if not admin_user:
                admin_user = User(
                    id=uuid.uuid4(),
                    email="admin_cors@ofc360.com",
                    hashed_password="pwd",
                    role="ADMIN",
                    company_id=comp.id
                )
                session.add(admin_user)
                await session.commit()
                await session.refresh(admin_user)

            claims = {
                "sub": str(admin_user.id),
                "role": admin_user.role,
                "company_id": str(comp.id),
            }
            token = create_access_token(claims)
            return token

    token = asyncio.run(get_test_token())
    headers = {
        "Origin": origin,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print("\n==================================================")
    print("TEST 3: PUT /api/v1/employees/{target_id} with full payload")
    print("==================================================")
    payload = {
        "first_name": "Rubel",
        "last_name": "SIngh Thakur",
        "personal_email": "rubelthakur614@gmail.com",
        "company_email": "rubelthakur614@gmail.com",
        "phone": "08580625010",
        "date_of_birth": "1995-05-15",
        "gender": "Male",
        "blood_group": "O+",
        "marital_status": "Single",
        "joining_date": "2026-08-04",
        "department": "Engineering",
        "designation": "Junior Developer",
        "role": "junior developer",
        "employment_type": "FULL_TIME",
        "branch": "Mumbai HQ",
        "work_location": "Onsite",
        "shift": "Morning",
        "leave_group": "Standard India Policy",
        "cost_center_id": "CC-ENG-01",
        "ctc": 7200000,
        "bonus": 180000,
        "hra": 300000
    }
    res_put = client.put(f"/api/v1/employees/{target_id}", json=payload, headers=headers)
    print(f"Status Code: {res_put.status_code}")
    print(f"Access-Control-Allow-Origin: {res_put.headers.get('access-control-allow-origin')}")
    print(f"Response Body: {res_put.json()}")
    assert res_put.status_code == 200
    assert res_put.headers.get("access-control-allow-origin") == origin
    data = res_put.json()["data"]
    assert data["first_name"] == "Rubel"
    assert data["last_name"] == "SIngh Thakur"

    print("\n==================================================")
    print("TEST 4: GET /api/v1/employees/{target_id}")
    print("==================================================")
    res_get = client.get(f"/api/v1/employees/{target_id}", headers=headers)
    print(f"Status Code: {res_get.status_code}")
    print(f"Access-Control-Allow-Origin: {res_get.headers.get('access-control-allow-origin')}")
    assert res_get.status_code == 200
    assert res_get.headers.get("access-control-allow-origin") == origin
    get_data = res_get.json()["data"]
    assert get_data["first_name"] == "Rubel"

    print("\n==================================================")
    print("CORS AND PUT TESTS ALL PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    test_cors_and_put()
