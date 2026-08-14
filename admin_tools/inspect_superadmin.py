import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as s:
        res = await s.execute(text("SELECT id, email, name, role, phone, is_active, is_verified, company_id FROM users"))
        users = res.fetchall()
        print("=== USERS IN DB ===")
        for u in users:
            print(dict(u._mapping))
        
        tables_res = await s.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = [t[0] for t in tables_res.fetchall()]
        print("\n=== RELEVANT TABLES ===")
        for t in tables:
            if any(k in t for k in ["log", "audit", "session", "user", "access", "track", "history"]):
                print(t)

if __name__ == "__main__":
    asyncio.run(check())
