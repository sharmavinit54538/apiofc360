import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT id, email, role FROM users WHERE email='sharmav33496@gmail.com'"))
        user = res.fetchone()
        print("USER IN DB:", user)
        if user:
            if user[2] != 'cto':
                await session.execute(text("UPDATE users SET role='cto' WHERE email='sharmav33496@gmail.com'"))
                await session.commit()
                print("UPDATED USER ROLE TO cto IN DB")
            else:
                print("USER IS ALREADY CTO ROLE IN DB")
        else:
            print("USER NOT FOUND IN DB")

if __name__ == "__main__":
    asyncio.run(check())
