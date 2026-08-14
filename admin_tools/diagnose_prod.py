import asyncio
import httpx

async def diagnose():
    base = "https://api.ofc360.com"
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check health
        try:
            r = await client.get(f"{base}/health")
            print(f"/health -> {r.status_code}: {r.text}")
        except Exception as e:
            print(f"/health error: {e}")

        # Check /api/v1/auth/status
        try:
            r = await client.get(f"{base}/api/v1/auth/status")
            print(f"/api/v1/auth/status -> {r.status_code}: {r.text}")
        except Exception as e:
            print(f"/api/v1/auth/status error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose())
