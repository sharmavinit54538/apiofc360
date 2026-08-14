import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal
from app.core.security import verify_password

async def verify():
    async with AsyncSessionLocal() as s:
        res = await s.execute(text("SELECT id, email, name, role, is_active, is_verified, password_hash FROM users WHERE role='super_admin'"))
        rows = res.fetchall()
        for r in rows:
            user_dict = dict(r._mapping)
            pwd_ok = verify_password("SuperAdmin@2026", user_dict["password_hash"])
            print(f"User: {user_dict['email']} | Role: {user_dict['role']} | Active: {user_dict['is_active']} | Verified: {user_dict['is_verified']} | Password Valid: {pwd_ok}")

if __name__ == "__main__":
    asyncio.run(verify())
