import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        for tbl in ['users', 'employees', 'companies', 'departments', 'employee_leave_policies', 'otp_codes']:
            res = await session.execute(text(f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = '{tbl}'
                ORDER BY ordinal_position;
            """))
            print(f"=== TABLE: {tbl} ===")
            for row in res.fetchall():
                print(dict(row._mapping))
            print()

if __name__ == "__main__":
    asyncio.run(main())
