import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text
from app.core.security import hash_password

async def reset_pass():
    async with AsyncSessionLocal() as session:
        h = hash_password("Password123!")
        await session.execute(text("UPDATE users SET password_hash=:h WHERE email='sharmav33496@gmail.com'"), {"h": h})
        await session.commit()
        print("RESET PASSWORD FOR sharmav33496@gmail.com TO Password123!")

if __name__ == "__main__":
    asyncio.run(reset_pass())
