import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        # Check company or companies or tenants table
        res = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = [r[0] for r in res.fetchall()]

        for t in ["companies", "tenants", "organizations", "company_profiles"]:
            if t in tables:
                r = await session.execute(text(f"SELECT * FROM {t} LIMIT 3"))
                print(f"Table {t}:", [dict(x._mapping) for x in r.fetchall()])

        # Fetch vinit sharma's real employee record from DB
        v = await session.execute(text("SELECT * FROM employees WHERE LOWER(first_name) LIKE '%vinit%' OR LOWER(last_name) LIKE '%vinit%'"))
        print("Vinit record:", [dict(x._mapping) for x in v.fetchall()])

if __name__ == "__main__":
    asyncio.run(main())
