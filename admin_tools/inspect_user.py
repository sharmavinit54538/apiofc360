import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as s:
        res = await s.execute(text("SELECT * FROM users WHERE email='sharmavinit7348@gmail.com'"))
        row = res.fetchone()
        if row:
            print("=== USER SHARMAVINIT7348 ===")
            for k, v in zip(res.keys(), row):
                print(f"{k}: {v}")
        
        comp = await s.execute(text("SELECT * FROM companies"))
        print("\n=== COMPANIES ===")
        for c in comp.fetchall():
            print(dict(c._mapping))

if __name__ == "__main__":
    asyncio.run(check())
