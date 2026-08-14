import asyncio
import httpx

async def test_register():
    base = "https://api.ofc360.com/api/v1"
    
    # 1. Register super admin
    payload = {
        "name": "Vinit Sharma",
        "email": "sharmavinit7348@gmail.com",
        "phone": "9351608590",
        "password": "SecureOfc#2026!",
        "company_name": "OFC360 Enterprise"
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{base}/auth/register", json=payload)
        print(f"Register status: {r.status_code}, response: {r.text}")

if __name__ == "__main__":
    asyncio.run(test_register())
