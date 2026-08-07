import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from app.db.database import AsyncSessionLocal
from sqlalchemy import text, select
from app.models.user import User

CTO_USER_EMAIL = os.getenv("CTO_USER_EMAIL", "cto@example.com")

async def fix_cto():
    async with AsyncSessionLocal() as session:
        # Update role to uppercase 'CTO'
        await session.execute(text("UPDATE users SET role='CTO' WHERE email=:email"), {"email": CTO_USER_EMAIL})
        await session.execute(text("UPDATE employees SET role='CTO' WHERE company_email=:email OR personal_email=:email"), {"email": CTO_USER_EMAIL})
        await session.commit()
        print("Updated role to 'CTO' in DB.")

        # Test SQLAlchemy ORM query
        stmt = select(User).where(User.email == CTO_USER_EMAIL)
        user_orm = (await session.execute(stmt)).scalar_one_or_none()
        if user_orm:
            print("ORM USER QUERY SUCCESS! User role:", user_orm.role, type(user_orm.role))

if __name__ == "__main__":
    asyncio.run(fix_cto())
