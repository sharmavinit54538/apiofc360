import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as session:
        u = await session.execute(text("SELECT * FROM users WHERE email='sharmav33496@gmail.com'"))
        row = u.fetchone()
        if row:
            print("USER COLS & VALUES:")
            for col, val in zip(u.keys(), row):
                print(f"  {col}: {val}")

        e = await session.execute(text("SELECT * FROM employees WHERE user_id='776cefbb-9138-49a1-985d-e4e835c036a5'"))
        erow = e.fetchone()
        if erow:
            print("\nEMPLOYEE COLS & VALUES:")
            for col, val in zip(e.keys(), erow):
                print(f"  {col}: {val}")

if __name__ == "__main__":
    asyncio.run(check())
