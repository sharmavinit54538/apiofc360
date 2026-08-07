import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def update_profile():
    async with AsyncSessionLocal() as session:
        # Update users table
        await session.execute(text("""
            UPDATE users 
            SET role = 'cto' 
            WHERE email = 'sharmav33496@gmail.com'
        """))

        # Update employees table
        await session.execute(text("""
            UPDATE employees 
            SET designation = 'Chief Technology Officer', 
                department = 'Technology',
                role = 'cto'
            WHERE company_email = 'sharmav33496@gmail.com' OR personal_email = 'sharmav33496@gmail.com' OR user_id = '776cefbb-9138-49a1-985d-e4e835c036a5'
        """))

        await session.commit()
        print("SUCCESSFULLY UPDATED DB PROFILE FOR SHARMAV33496@GMAIL.COM")

if __name__ == "__main__":
    asyncio.run(update_profile())
