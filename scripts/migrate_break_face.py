"""Database schema migration script for AttendanceBreak face verification & geofence columns."""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import text
from app.db.database import AsyncSessionLocal


async def migrate():
    async with AsyncSessionLocal() as session:
        print("Migrating attendance_breaks table for Face Attendance Biometrics...")

        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS start_image_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS end_image_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS start_face_distance DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS end_face_distance DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS start_liveness_score DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS end_liveness_score DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS start_latitude DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS start_longitude DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS end_latitude DOUBLE PRECISION;"))
        await session.execute(text("ALTER TABLE attendance_breaks ADD COLUMN IF NOT EXISTS end_longitude DOUBLE PRECISION;"))

        await session.commit()
        print("attendance_breaks migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
