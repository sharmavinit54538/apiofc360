import asyncio
from app.db.database import engine
from sqlalchemy import text

async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE fnf_settlements ADD COLUMN IF NOT EXISTS gratuity NUMERIC(14, 2) NOT NULL DEFAULT 0.0;"))
        print("Successfully ensured gratuity column in fnf_settlements.")

asyncio.run(migrate())
