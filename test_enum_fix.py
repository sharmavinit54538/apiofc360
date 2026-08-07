import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text
from app.models.user import User

async def test():
    async with AsyncSessionLocal() as session:
        # Check database values in users table for role
        res = await session.execute(text("SELECT id, email, role FROM users WHERE email='sharmav33496@gmail.com'"))
        row = res.fetchone()
        print("RAW DB ROW:", row)

        try:
            # Attempt to query via SQLAlchemy ORM
            from sqlalchemy import select
            stmt = select(User).where(User.email == 'sharmav33496@gmail.com')
            user_orm = (await session.execute(stmt)).scalar_one_or_none()
            print("ORM USER SUCCESS:", user_orm.email, user_orm.role)
        except Exception as e:
            print("ORM USER ERROR:", type(e), e)

if __name__ == "__main__":
    asyncio.run(test())
