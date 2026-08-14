import asyncio
import httpx

async def check_endpoints():
    async with httpx.AsyncClient() as client:
        # Check health
        try:
            r = await client.get("https://api.ofc360.com/health")
            print(f"/health status: {r.status_code}, text: {r.text}")
        except Exception as e:
            print(f"/health error: {e}")

        # Check /api/v1/auth/status
        try:
            r = await client.get("https://api.ofc360.com/api/v1/auth/status")
            print(f"/api/v1/auth/status status: {r.status_code}, text: {r.text}")
        except Exception as e:
            print(f"/api/v1/auth/status error: {e}")

        # Test login with admin@test.com
        try:
            r = await client.post("https://api.ofc360.com/api/v1/auth/login", json={"email": "admin@test.com", "password": "Password123!"})
            print(f"login admin@test.com with Password123!: {r.status_code}, {r.text}")
        except Exception as e:
            print(f"login error: {e}")

        # Test login with superadmin@ofc360.com
        try:
            r = await client.post("https://api.ofc360.com/api/v1/auth/login", json={"email": "superadmin@ofc360.com", "password": "Password123!"})
            print(f"login superadmin with Password123!: {r.status_code}, {r.text}")
        except Exception as e:
            print(f"login error: {e}")

if __name__ == "__main__":
    asyncio.run(check_endpoints())
