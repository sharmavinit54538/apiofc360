import asyncio
from app.db.database import AsyncSessionLocal
from sqlalchemy import text
from sqlalchemy import select
from app.models.user import User

async def update_ceo():
    async with AsyncSessionLocal() as session:
        # Update user siddhubunny09@gmail.com
        res = await session.execute(text("SELECT id, email, role FROM users WHERE LOWER(email)='siddhubunny09@gmail.com'"))
        user_row = res.fetchone()
        print("FOUND USER ROW IN DB:", user_row)

        if user_row:
            await session.execute(text("UPDATE users SET role='CEO' WHERE LOWER(email)='siddhubunny09@gmail.com'"))
            await session.execute(text("UPDATE users SET role='ceo' WHERE LOWER(email)='siddhubunny09@gmail.com'"))
            print("UPDATED users table role to 'CEO' / 'ceo'")

        # Update employee row if exists
        res_emp = await session.execute(text("SELECT id, company_email, personal_email, role FROM employees WHERE LOWER(company_email)='siddhubunny09@gmail.com' OR LOWER(personal_email)='siddhubunny09@gmail.com'"))
        emp_rows = res_emp.fetchall()
        print("FOUND EMPLOYEE ROWS IN DB:", emp_rows)

        if emp_rows:
            await session.execute(text("UPDATE employees SET role='CEO' WHERE LOWER(company_email)='siddhubunny09@gmail.com' OR LOWER(personal_email)='siddhubunny09@gmail.com'"))
            await session.execute(text("UPDATE employees SET designation='CEO', department='Executive Board' WHERE LOWER(company_email)='siddhubunny09@gmail.com' OR LOWER(personal_email)='siddhubunny09@gmail.com'"))
            print("UPDATED employees table role to 'CEO'")

        await session.commit()
        print("DATABASE COMMIT SUCCESSFUL FOR siddhubunny09@gmail.com!")

if __name__ == "__main__":
    asyncio.run(update_ceo())
