import asyncio
import httpx
import time

async def check_prod():
    url = "https://api.ofc360.com/api/v1/auth/login"
    payload = {
        "email": "superadmin@ofc360.com",
        "password": "SuperAdmin@2026"
    }
    
    print("Waiting for Render deployment to complete...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(12):
            try:
                res = await client.post(url, json=payload)
                print(f"Attempt {i+1}: Status={res.status_code}, Body={res.text[:120]}")
                if res.status_code == 200:
                    print("SUCCESS! Live production backend login returned 200 OK!")
                    return
            except Exception as e:
                print(f"Attempt {i+1}: Exception={e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(check_prod())
