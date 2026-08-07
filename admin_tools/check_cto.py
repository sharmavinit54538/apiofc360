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
        res = await session.execute(text("SELECT id, email, role FROM users WHERE email=:email"), {"email": CTO_USER_EMAIL})
        user = res.fetchone()
        print("USER IN DB:", user)
        if user:
            if user[2] != 'cto':
                await session.execute(text("UPDATE users SET role='cto' WHERE email=:email"), {"email": CTO_USER_EMAIL})
                await session.commit()
                print("UPDATED USER ROLE TO cto IN DB")
            else:
                print("USER IS ALREADY CTO ROLE IN DB")
        else:
            print("USER NOT FOUND IN DB")

if __name__ == "__main__":
    asyncio.run(check())
