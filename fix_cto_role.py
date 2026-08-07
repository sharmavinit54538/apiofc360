import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text
from sqlalchemy import select
from app.models.user import User

async def fix_cto():
    async with AsyncSessionLocal() as session:
        # Update role to uppercase 'CTO'
        await session.execute(text("UPDATE users SET role='CTO' WHERE email='sharmav33496@gmail.com'"))
        await session.execute(text("UPDATE employees SET role='CTO' WHERE company_email='sharmav33496@gmail.com' OR personal_email='sharmav33496@gmail.com' OR user_id='776cefbb-9138-49a1-985d-e4e835c036a5'"))
        await session.commit()
        print("Updated role to 'CTO' in DB.")

        # Test SQLAlchemy ORM query
        stmt = select(User).where(User.email == 'sharmav33496@gmail.com')
        user_orm = (await session.execute(stmt)).scalar_one_or_none()
        print("ORM USER QUERY SUCCESS! User role:", user_orm.role, type(user_orm.role))

if __name__ == "__main__":
    asyncio.run(fix_cto())
