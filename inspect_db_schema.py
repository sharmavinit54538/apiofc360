import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        print("=== 1. EMPLOYEES TABLE COLUMNS ===")
        res = await session.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'employees'
            ORDER BY ordinal_position;
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n=== 2. EMPLOYEES TABLE CONSTRAINTS & INDEXES ===")
        res = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'employees'::regclass;
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n=== 3. CHECK SPECIFIC EMPLOYEE e7f1f422-2dab-40a1-8101-16102b9c2e65 ===")
        emp_id = uuid.UUID("e7f1f422-2dab-40a1-8101-16102b9c2e65")
        res = await session.execute(text("SELECT * FROM employees WHERE id = :id"), {"id": emp_id})
        emp_row = res.fetchone()
        print("Employee e7f1f422-2dab-40a1-8101-16102b9c2e65:", dict(emp_row._mapping) if emp_row else "NOT FOUND")

        print("\n=== 4. CHECK USERS TABLE ===")
        res = await session.execute(text("SELECT id, email, role, company_id FROM users LIMIT 10;"))
        for r in res.fetchall():
            print(dict(r._mapping))

        print("\n=== 5. CHECK COMPANIES TABLE ===")
        res = await session.execute(text("SELECT id, name FROM companies LIMIT 10;"))
        for r in res.fetchall():
            print(dict(r._mapping))

if __name__ == "__main__":
    asyncio.run(main())
