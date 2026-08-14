import asyncio
import httpx

async def test_forgot():
    base = "https://api.ofc360.com/api/v1"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{base}/auth/forgot-password", json={"email": "sharmavinit7348@gmail.com"})
        print(f"Forgot password response: {r.status_code}, {r.text}")

if __name__ == "__main__":
    asyncio.run(test_forgot())
