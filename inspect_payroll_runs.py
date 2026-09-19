import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())
from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'payroll_runs'
            ORDER BY ordinal_position;
        """))
        print('=== PAYROLL_RUNS COLUMNS ===')
        for r in res.fetchall():
            print(dict(r._mapping))

if __name__ == "__main__":
    asyncio.run(check())
