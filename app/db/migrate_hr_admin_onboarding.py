"""Direct migration script for HR Admin Onboarding database tables and columns."""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.getcwd())

from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def run():
    async with AsyncSessionLocal() as session:
        statements = [
            # 1. Create employee_invitations table if not exists
            """
            CREATE TABLE IF NOT EXISTS employee_invitations (
                id UUID PRIMARY KEY,
                company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
                employee_name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                department VARCHAR(100),
                designation VARCHAR(100),
                token VARCHAR(128) UNIQUE NOT NULL,
                token_hash VARCHAR(128),
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Indexes for employee_invitations
            "CREATE INDEX IF NOT EXISTS ix_employee_invitations_company_id ON employee_invitations(company_id);",
            "CREATE INDEX IF NOT EXISTS ix_employee_invitations_email ON employee_invitations(email);",
            "CREATE INDEX IF NOT EXISTS ix_employee_invitations_status ON employee_invitations(status);",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_employee_invitation ON employee_invitations(company_id, LOWER(email)) WHERE status = 'PENDING';",
            
            # 2. Add missing columns to onboarding_progress
            "ALTER TABLE onboarding_progress ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;",
            "ALTER TABLE onboarding_progress ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'not_started';",
            "ALTER TABLE onboarding_progress ADD COLUMN IF NOT EXISTS completed_steps JSON;",
            "ALTER TABLE onboarding_progress ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE onboarding_progress ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;",

            # 3. Add missing columns to leave_policies
            "ALTER TABLE leave_policies ADD COLUMN IF NOT EXISTS leave_type VARCHAR(50) DEFAULT 'ANNUAL';",
            "ALTER TABLE leave_policies ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';",

            # 4. Add company status column if missing
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'PENDING';",
        ]

        for stmt in statements:
            await session.execute(text(stmt))

        await session.commit()
        print("Successfully applied HR Admin Onboarding schema migrations!")


if __name__ == "__main__":
    asyncio.run(run())
