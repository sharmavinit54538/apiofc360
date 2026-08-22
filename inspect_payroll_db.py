import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'payslips'::regclass;
        """))
        print('=== PAYSLIPS CONSTRAINTS ===')
        for r in res.fetchall():
            print(dict(r._mapping))
            
        res2 = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'pay_cycles'::regclass;
        """))
        print('=== PAY_CYCLES CONSTRAINTS ===')
        for r in res2.fetchall():
            print(dict(r._mapping))

        res3 = await session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'payslips'
            ORDER BY ordinal_position;
        """))
        print('=== PAYSLIPS COLUMNS ===')
        for r in res3.fetchall():
            print(dict(r._mapping))

if __name__ == "__main__":
    asyncio.run(check())
