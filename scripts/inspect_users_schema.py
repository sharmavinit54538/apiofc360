import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        print("=== USERS TABLE CONSTRAINTS ===")
        res = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'users'::regclass;
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n=== USERS TABLE COLUMNS ===")
        res = await session.execute(text("""
            SELECT column_name, udt_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'role';
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

if __name__ == "__main__":
    asyncio.run(main())
