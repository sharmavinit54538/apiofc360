import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal

async def test_db_link():
    test_email = "test_probe_987@ofc360.com"
    base = "https://api.ofc360.com/api/v1"
    
    # 1. Register on live api
    reg_payload = {
        "name": "Alex Hunter",
        "email": test_email,
        "phone": "9811223344",
        "password": "SecureOfc#2026!",
        "company_name": "Probe Enterprise"
    }
    
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{base}/auth/register", json=reg_payload)
        print(f"Live API Register Status: {r.status_code}, Response: {r.text}")
    
    # 2. Check if this test user appears in our Render Postgres database
    async with AsyncSessionLocal() as s:
        res = await s.execute(text("SELECT id, email, role, is_active FROM users WHERE email=:email"), {"email": test_email})
        row = res.fetchone()
        if row:
            print(f"FOUND IN RENDER DB! -> {dict(row._mapping)}")
            print("CONCLUSION: Live server IS connected to the Render DB!")
        else:
            print("NOT FOUND IN RENDER DB!")
            print("CONCLUSION: Live server is connected to a DIFFERENT database (e.g. local Docker postgres)!")

if __name__ == "__main__":
    asyncio.run(test_db_link())
