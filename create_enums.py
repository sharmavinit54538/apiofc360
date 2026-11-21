import asyncio
from sqlalchemy import text
from app.db.database import AsyncSessionLocal

async def create_enums():
    async with AsyncSessionLocal() as session:
        await session.execute(text("CREATE TYPE maintenance_status AS ENUM ('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')"))
        await session.execute(text("CREATE TYPE asset_request_type AS ENUM ('NEW_ASSET', 'REPLACEMENT', 'PERIPHERAL', 'UPGRADE', 'ACCESSORY')"))
        await session.execute(text("CREATE TYPE asset_request_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'FULFILLED', 'CANCELLED')"))
        await session.commit()
        print('Enums created successfully')

asyncio.run(create_enums())