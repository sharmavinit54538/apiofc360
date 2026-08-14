import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        print("=== USER_ROLE ENUM VALUES IN DB ===")
        res = await session.execute(text("""
            SELECT t.typname, e.enumlabel, e.enumsortorder
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            WHERE t.typname = 'user_role'
            ORDER BY e.enumsortorder;
        """))
        rows = res.fetchall()
        for r in rows:
            print(dict(r._mapping))

        print("\n=== CURRENT USERS IN DB ===")
        res = await session.execute(text("""
            SELECT id, email, phone, role, is_active, is_verified, company_id FROM users;
        """))
        for r in res.fetchall():
            print(dict(r._mapping))

        print("\n=== CURRENT EMPLOYEES IN DB ===")
        res = await session.execute(text("""
            SELECT id, user_id, employee_id, personal_email, phone, role, status FROM employees;
        """))
        for r in res.fetchall():
            print(dict(r._mapping))

if __name__ == "__main__":
    asyncio.run(main())
