import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

CTO_USER_EMAIL = os.getenv("CTO_USER_EMAIL", "cto@example.com")

async def check():
    async with AsyncSessionLocal() as session:
        u = await session.execute(text("SELECT * FROM users WHERE email=:email"), {"email": CTO_USER_EMAIL})
        row = u.fetchone()
        if row:
            print("USER COLS & VALUES:")
            for col, val in zip(u.keys(), row):
                print(f"  {col}: {val}")

        e = await session.execute(text("SELECT * FROM employees WHERE company_email=:email OR personal_email=:email"), {"email": CTO_USER_EMAIL})
        erow = e.fetchone()
        if erow:
            print("\nEMPLOYEE COLS & VALUES:")
            for col, val in zip(e.keys(), erow):
                print(f"  {col}: {val}")

if __name__ == "__main__":
    asyncio.run(check())
