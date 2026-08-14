import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.getcwd())
from app.main import app

async def run_tests():
    print("========================================")
    print("STARTING LIVE FASTAPI ASGI LOGIN TESTS")
    print("========================================")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Test 1: Super Admin login (superadmin@ofc360.com)
        print("\n[TEST 1] Logging in with superadmin@ofc360.com...")
        res1 = await client.post("/api/v1/auth/login", json={
            "identifier": "superadmin@ofc360.com",
            "password": "SuperAdmin@2026"
        })
        print(f"Status Code: {res1.status_code}")
        body1 = res1.json()
        print(f"Response: success={body1.get('success')}, message={body1.get('message')}")
        if res1.status_code == 200:
            user_info = body1["data"]["user"]
            token = body1["data"]["access_token"]
            print(f"User: {user_info['name']} | Role: {user_info['role']} | Email: {user_info['email']}")
            print(f"Access Token generated: {token[:25]}...")
        else:
            print("FAILED BODY:", body1)
            assert False, f"Test 1 failed with status {res1.status_code}"

        # Test 2: Personal Super Admin login (sharmavinit7348@gmail.com)
        print("\n[TEST 2] Logging in with sharmavinit7348@gmail.com...")
        res2 = await client.post("/api/v1/auth/login", json={
            "identifier": "sharmavinit7348@gmail.com",
            "password": "SuperAdmin@2026"
        })
        print(f"Status Code: {res2.status_code}")
        body2 = res2.json()
        print(f"Response: success={body2.get('success')}, message={body2.get('message')}")
        if res2.status_code == 200:
            user_info = body2["data"]["user"]
            print(f"User: {user_info['name']} | Role: {user_info['role']} | Email: {user_info['email']}")
        else:
            print("FAILED BODY:", body2)
            assert False, f"Test 2 failed with status {res2.status_code}"

        # Test 3: Wrong password test (Should return 401, NOT 500)
        print("\n[TEST 3] Testing incorrect password...")
        res3 = await client.post("/api/v1/auth/login", json={
            "identifier": "superadmin@ofc360.com",
            "password": "WrongPassword123!"
        })
        print(f"Status Code: {res3.status_code} (Expected 401)")
        print(f"Response: {res3.json()}")
        assert res3.status_code == 401, f"Expected 401, got {res3.status_code}"

        # Test 4: Non-existent user test (Should return 401, NOT 500)
        print("\n[TEST 4] Testing non-existent user...")
        res4 = await client.post("/api/v1/auth/login", json={
            "identifier": "doesnotexist_random_12345@test.com",
            "password": "Password123!"
        })
        print(f"Status Code: {res4.status_code} (Expected 401)")
        print(f"Response: {res4.json()}")
        assert res4.status_code == 401, f"Expected 401, got {res4.status_code}"

        # Test 5: Super Admin Access to Super Admin Endpoints with Token
        print("\n[TEST 5] Accessing /api/v1/super-admin/dashboard with generated token...")
        auth_headers = {"Authorization": f"Bearer {token}"}
        res5 = await client.get("/api/v1/super-admin/dashboard", headers=auth_headers)
        print(f"Dashboard Status Code: {res5.status_code}")
        print(f"Dashboard Data: {res5.json()}")
        assert res5.status_code == 200, f"Expected 200, got {res5.status_code}"

        print("\n[TEST 6] Accessing /api/v1/super-admin/organizations...")
        res6 = await client.get("/api/v1/super-admin/organizations", headers=auth_headers)
        print(f"Organizations Status Code: {res6.status_code}")
        print(f"Organizations Count: {len(res6.json())}")
        assert res6.status_code == 200, f"Expected 200, got {res6.status_code}"

        print("\n[TEST 7] Accessing /api/v1/super-admin/users...")
        res7 = await client.get("/api/v1/super-admin/users", headers=auth_headers)
        print(f"Users Status Code: {res7.status_code}")
        print(f"Users Count: {len(res7.json())}")
        assert res7.status_code == 200, f"Expected 200, got {res7.status_code}"

    print("\n========================================")
    print("ALL TESTS PASSED! ZERO 500 ERRORS!")
    print("========================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
