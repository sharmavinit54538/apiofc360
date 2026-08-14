import asyncio
import httpx

async def test_auth_features():
    base = "https://api.ofc360.com/api/v1"
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Test register with a fresh test super admin
        reg_payload = {
            "name": "Super Admin Master",
            "email": "superadmin_new@ofc360.com",
            "phone": "9876543210",
            "password": "SuperAdmin@2026",
            "company_name": "OFC360 Master"
        }
        try:
            r = await client.post(f"{base}/auth/register", json=reg_payload)
            print(f"Register attempt: {r.status_code}, text: {r.text}")
        except Exception as e:
            print(f"Register error: {e}")

if __name__ == "__main__":
    asyncio.run(test_auth_features())
