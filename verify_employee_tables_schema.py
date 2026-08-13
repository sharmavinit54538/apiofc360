import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.db.base import Base
import app.models  # load all models
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        emp_tables = [
            "employees",
            "employee_addresses",
            "employee_bank_accounts",
            "employee_documents",
            "employee_education",
            "employee_emergency_contacts",
            "employee_experience",
            "employee_skills",
            "employee_leave_policies",
            "employee_onboardings"
        ]
        
        for mapper in Base.registry.mappers:
            cls = mapper.class_
            tablename = cls.__tablename__
            if tablename not in emp_tables:
                continue

            res = await session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t;
            """), {"t": tablename})
            db_cols = set(r[0] for r in res.fetchall())
            model_cols = set(c.key for c in mapper.columns)
            
            missing_in_db = model_cols - db_cols
            if missing_in_db:
                print(f"[MISMATCH] Table '{tablename}' ({cls.__name__}): Columns in model but MISSING in DB: {missing_in_db}")
            else:
                print(f"[OK] Table '{tablename}' ({cls.__name__}) matches DB perfectly.")

if __name__ == "__main__":
    asyncio.run(main())
