import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

SEARCH_NAME = os.getenv("SEARCH_EMPLOYEE_NAME", "vinit")

async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = [r[0] for r in res.fetchall()]

        for t in ["companies", "tenants", "organizations", "company_profiles"]:
            if t in tables:
                r = await session.execute(text(f"SELECT * FROM {t} LIMIT 3"))
                print(f"Table {t}:", [dict(x._mapping) for x in r.fetchall()])

        v = await session.execute(
            text("SELECT * FROM employees WHERE LOWER(first_name) LIKE :pattern OR LOWER(last_name) LIKE :pattern"),
            {"pattern": f"%{SEARCH_NAME.lower()}%"}
        )
        print("Matching employee records:", [dict(x._mapping) for x in v.fetchall()])

if __name__ == "__main__":
    asyncio.run(main())
