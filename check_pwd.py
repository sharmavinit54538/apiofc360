"""Verify and reset password hash in one script."""
import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

async def run():
    from app.db.database import AsyncSessionLocal
    from app.models.user import User
    from app.core.security import verify_password, hash_password
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.email == "sharmavinit7348@gmail.com"))
        user = res.scalar_one_or_none()
        if user:
            print("User found:", user.email)
            print("Hash:", user.password_hash)
            match = verify_password("Password123!", user.password_hash)
            print("Match for Password123!:", match)
            if not match:
                user.password_hash = hash_password("Password123!")
                await session.commit()
                print("Password has been reset to Password123!")
        else:
            print("User not found!")

asyncio.run(run())
