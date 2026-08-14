import asyncio
import httpx
import sys

async def check():
    url = "https://api.ofc360.com/api/v1/auth/login"
    payload = {
        "email": "superadmin@ofc360.com",
        "password": "SuperAdmin@2026"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, json=payload)
            print(f"Status: {res.status_code}", flush=True)
            print(f"Body: {res.text}", flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)

if __name__ == "__main__":
    asyncio.run(check())
