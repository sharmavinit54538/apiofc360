import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check_roles():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT DISTINCT role FROM users"))
        print("DISTINCT ROLES IN USERS TABLE:", res.fetchall())

if __name__ == "__main__":
    asyncio.run(check_roles())
