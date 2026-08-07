import asyncio
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check_roles():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT DISTINCT role FROM users"))
        print("DISTINCT ROLES IN USERS TABLE:", res.fetchall())

if __name__ == "__main__":
    asyncio.run(check_roles())
