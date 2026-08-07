import asyncio, sys, os
sys.path.insert(0, 'd:/new')
os.chdir('d:/new')
from dotenv import load_dotenv
load_dotenv()
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

asyncio.run(main())
