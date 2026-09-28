"""Database schema migration script for Face Attendance biometric enrollment columns."""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text


async def migrate():
    async with AsyncSessionLocal() as session:
        print("Migrating database schema for Face Attendance Biometric support...")

        # 1. Update employees table
        print("Updating employees table...")
        await session.execute(text("ALTER TABLE employees ADD COLUMN IF NOT EXISTS face_embedding JSONB;"))
        await session.execute(text("ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_face_enrolled BOOLEAN NOT NULL DEFAULT FALSE;"))
        await session.execute(text("ALTER TABLE employees ADD COLUMN IF NOT EXISTS face_enrolled_at TIMESTAMP WITH TIME ZONE;"))

        # 2. Update users table
        print("Updating users table...")
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_face_enrolled BOOLEAN NOT NULL DEFAULT FALSE;"))
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS face_enrolled_at TIMESTAMP WITH TIME ZONE;"))

        # 3. Update attendances table
        print("Updating attendances table...")
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS captured_face_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'Present';"))
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS punch_type VARCHAR(10) NOT NULL DEFAULT 'IN';"))
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT TRUE;"))
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS punch_verified_by VARCHAR(20) DEFAULT 'FACE';"))
        await session.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS notes VARCHAR(500);"))

        await session.commit()
        print("Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
