"""Direct schema migration runner to ensure account_status, verification token, and FK columns exist."""

import asyncio
from sqlalchemy import text
from app.db.database import AsyncSessionLocal


async def run():
    async with AsyncSessionLocal() as session:
        statements = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status VARCHAR(50) NOT NULL DEFAULT 'PENDING_EMAIL_VERIFICATION'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
            """UPDATE users
               SET account_status = CASE
                   WHEN is_active = TRUE AND is_verified = TRUE THEN 'ACTIVE'
                   WHEN is_active = FALSE AND is_verified = TRUE THEN 'SUSPENDED'
                   ELSE 'PENDING_EMAIL_VERIFICATION'
               END
               WHERE account_status IS NULL OR account_status = 'PENDING_EMAIL_VERIFICATION'""",
        ]
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()
        print("Successfully applied schema updates to users table!")


if __name__ == "__main__":
    asyncio.run(run())
