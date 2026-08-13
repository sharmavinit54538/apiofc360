import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        print("Adding missing columns to employee_bank_accounts & employee_experience if not exist...")
        # Bank accounts
        await session.execute(text("ALTER TABLE employee_bank_accounts ADD COLUMN IF NOT EXISTS branch VARCHAR(100);"))
        await session.execute(text("ALTER TABLE employee_bank_accounts ADD COLUMN IF NOT EXISTS upi_id VARCHAR(50);"))
        await session.execute(text("ALTER TABLE employee_bank_accounts ADD COLUMN IF NOT EXISTS cancelled_cheque_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE employee_bank_accounts ADD COLUMN IF NOT EXISTS passbook_url VARCHAR(500);"))

        # Employee experience
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS ctc NUMERIC(14, 2);"))
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS manager_name VARCHAR(150);"))
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS reason_for_leaving TEXT;"))
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS experience_certificate_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS relieving_letter_url VARCHAR(500);"))
        await session.execute(text("ALTER TABLE employee_experience ADD COLUMN IF NOT EXISTS salary_slip_url VARCHAR(500);"))

        await session.commit()
        print("All missing columns added successfully.")

if __name__ == "__main__":
    asyncio.run(main())
