import asyncio
from app.db.database import engine
from sqlalchemy import text

async def inspect():
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'fnf_settlements' ORDER BY ordinal_position"))
        for col in res.fetchall():
            print(col)

asyncio.run(inspect())
