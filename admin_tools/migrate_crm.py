import asyncio
import sys
import os
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text(
                "ALTER TABLE candidate_crm_notes ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'note'"
            ))
            await session.execute(text(
                "ALTER TABLE candidate_crm_notes ADD COLUMN IF NOT EXISTS subject VARCHAR(300)"
            ))
            await session.commit()
            print("Migration successful: channel and subject columns added")
        except Exception as e:
            await session.rollback()
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
