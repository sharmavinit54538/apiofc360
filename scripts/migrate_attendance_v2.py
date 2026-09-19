"""Production-ready migration script for Face Attendance v2 schema.

Creates:
1. `attendance_breaks` table with indexes
2. `office_locations` table with indexes
3. Missing columns on `attendances` table
"""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import text
from app.db.database import AsyncSessionLocal


async def run_migration():
    print("Starting Face Attendance v2 database migration...")
    async with AsyncSessionLocal() as session:
        ddl_statements = [
            # 1. Update attendances table columns
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS location_accuracy DOUBLE PRECISION",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS break_duration DOUBLE PRECISION DEFAULT 0.0",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS liveness_score DOUBLE PRECISION",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS face_distance DOUBLE PRECISION",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS is_late BOOLEAN DEFAULT FALSE",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS late_minutes INTEGER DEFAULT 0",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS shift_id UUID",
            "ALTER TABLE attendances ADD COLUMN IF NOT EXISTS shift_name VARCHAR(100)",

            # 2. Create attendance_breaks table
            """
            CREATE TABLE IF NOT EXISTS attendance_breaks (
                id UUID PRIMARY KEY,
                attendance_id UUID NOT NULL REFERENCES attendances(id) ON DELETE CASCADE,
                employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
                company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
                break_start TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                break_end TIMESTAMP WITH TIME ZONE,
                duration_minutes DOUBLE PRECISION,
                status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                notes VARCHAR(500),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_attendance_breaks_attendance_id ON attendance_breaks(attendance_id)",
            "CREATE INDEX IF NOT EXISTS ix_attendance_breaks_employee_id ON attendance_breaks(employee_id)",
            "CREATE INDEX IF NOT EXISTS ix_attendance_breaks_company_id ON attendance_breaks(company_id)",
            "CREATE INDEX IF NOT EXISTS ix_attendance_breaks_status ON attendance_breaks(status)",

            # 3. Create office_locations table
            """
            CREATE TABLE IF NOT EXISTS office_locations (
                id UUID PRIMARY KEY,
                company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                name VARCHAR(150) NOT NULL,
                branch VARCHAR(100),
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                radius_meters DOUBLE PRECISION NOT NULL DEFAULT 200.0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_office_locations_company_id ON office_locations(company_id)",
            "CREATE INDEX IF NOT EXISTS ix_office_locations_branch ON office_locations(branch)",

            # 4. Ensure company geofence columns exist
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS office_latitude DOUBLE PRECISION",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS office_longitude DOUBLE PRECISION",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS geofence_radius_meters DOUBLE PRECISION DEFAULT 200.0",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) DEFAULT 'Asia/Kolkata'",
        ]

        for stmt in ddl_statements:
            await session.execute(text(stmt))

        await session.commit()
        print("Face Attendance v2 database migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_migration())
