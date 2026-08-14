import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal
from app.core.security import verify_password, hash_password

async def inspect():
    async with AsyncSessionLocal() as s:
        res = await s.execute(text("SELECT id, email, role, password_hash, is_active, is_verified, must_change_password FROM users"))
        rows = res.fetchall()
        print("=== ALL USERS IN DB ===")
        for r in rows:
            u = dict(r._mapping)
            print(f"Email: {u['email']}")
            print(f"Role: {u['role']}")
            print(f"Active: {u['is_active']}, Verified: {u['is_verified']}")
            print(f"Hash: {u['password_hash']}")
            print(f"Match SuperAdmin@2026: {verify_password('SuperAdmin@2026', u['password_hash'])}")
            print(f"Match Password123!: {verify_password('Password123!', u['password_hash'])}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(inspect())
