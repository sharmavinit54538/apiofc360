import asyncio
import httpx
import json

async def test_prod():
    async with httpx.AsyncClient() as client:
        # Test 1: superadmin@ofc360.com with identifier
        print("Testing superadmin with identifier...")
        r1 = await client.post(
            "https://api.ofc360.com/api/v1/auth/login",
            json={"identifier": "superadmin@ofc360.com", "password": "SuperAdmin@2026"}
        )
        print(f"R1 Status: {r1.status_code}, Body: {r1.text}")

        # Test 2: superadmin@ofc360.com with email
        print("\nTesting superadmin with email...")
        r2 = await client.post(
            "https://api.ofc360.com/api/v1/auth/login",
            json={"email": "superadmin@ofc360.com", "password": "SuperAdmin@2026"}
        )
        print(f"R2 Status: {r2.status_code}, Body: {r2.text}")

        # Test 3: sharmavinit7348@gmail.com with identifier
        print("\nTesting sharmavinit with identifier...")
        r3 = await client.post(
            "https://api.ofc360.com/api/v1/auth/login",
            json={"identifier": "sharmavinit7348@gmail.com", "password": "SuperAdmin@2026"}
        )
        print(f"R3 Status: {r3.status_code}, Body: {r3.text}")

        # Test 4: sharmavinit7348@gmail.com with email
        print("\nTesting sharmavinit with email...")
        r4 = await client.post(
            "https://api.ofc360.com/api/v1/auth/login",
            json={"email": "sharmavinit7348@gmail.com", "password": "SuperAdmin@2026"}
        )
        print(f"R4 Status: {r4.status_code}, Body: {r4.text}")

if __name__ == "__main__":
    asyncio.run(test_prod())
