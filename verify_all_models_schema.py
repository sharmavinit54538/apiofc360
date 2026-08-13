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
        print("=== VERIFYING ALL SQLALCHEMY MODELS AGAINST POSTGRES SCHEMA ===")
        mismatches = []
        for mapper in Base.registry.mappers:
            cls = mapper.class_
            tablename = cls.__tablename__
            
            # Get DB columns for this table
            res = await session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t;
            """), {"t": tablename})
            db_cols = set(r[0] for r in res.fetchall())
            
            if not db_cols:
                print(f"WARNING: Table '{tablename}' for model {cls.__name__} does not exist in DB!")
                continue

            # Model mapped column names
            model_cols = set(c.key for c in mapper.columns)
            
            missing_in_db = model_cols - db_cols
            if missing_in_db:
                print(f"[MISMATCH] Table '{tablename}' ({cls.__name__}): Columns in model but MISSING in DB: {missing_in_db}")
                mismatches.append((tablename, cls.__name__, missing_in_db))

        if not mismatches:
            print("\nALL MODELS MATCH DATABASE SCHEMA PERFECTLY!")
        else:
            print(f"\nFound {len(mismatches)} tables with schema mismatches:")
            for t, c, m in mismatches:
                print(f"  Table: {t} ({c}) -> Missing in DB: {m}")

if __name__ == "__main__":
    asyncio.run(main())
