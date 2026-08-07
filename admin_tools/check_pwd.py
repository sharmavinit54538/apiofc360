"""Verify and reset password hash in one script."""
import asyncio
import sys
import os
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "testuser@example.com")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "SecretPass123!")

async def run():
    from app.db.database import AsyncSessionLocal
    from app.models.user import User
    from app.core.security import verify_password, hash_password
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.email == TEST_USER_EMAIL))
        user = res.scalar_one_or_none()
        if user:
            print("User found:", user.email)
            print("Hash:", user.password_hash)
            match = verify_password(TEST_USER_PASSWORD, user.password_hash)
            print(f"Match for {TEST_USER_PASSWORD}:", match)
            if not match:
                user.password_hash = hash_password(TEST_USER_PASSWORD)
                await session.commit()
                print(f"Password has been reset to {TEST_USER_PASSWORD}")
        else:
            print("User not found!")

if __name__ == "__main__":
    asyncio.run(run())
