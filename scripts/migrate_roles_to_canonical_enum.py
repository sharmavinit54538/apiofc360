"""Standalone executable migration script to align legacy role representations to canonical RoleEnum."""

from __future__ import annotations

import asyncio
import logging
from sqlalchemy import text
from app.db.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_roles")


async def migrate_roles_to_canonical_enum():
    logger.info("Starting role standardization database migration...")
    async with engine.begin() as conn:
        # Check if user_role enum exists
        has_enum_res = await conn.execute(text("SELECT 1 FROM pg_type WHERE typname = 'user_role'"))
        has_enum = bool(has_enum_res.scalar())
        logger.info("PostgreSQL user_role native enum present: %s", has_enum)

        # 1. Standardize employees table
        has_emp_res = await conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='employees'"))
        if has_emp_res.scalar():
            logger.info("Standardizing employees table roles...")
            await conn.execute(text("""
                UPDATE employees
                SET role = CASE
                    WHEN LOWER(role) IN ('super_admin', 'superadmin', 'super_administrator') THEN 'super_admin'
                    WHEN LOWER(role) IN ('admin', 'hr', 'hr_admin', 'hradmin', 'hr_manager', 'payroll_admin', 'finance') THEN 'hr_admin'
                    WHEN LOWER(role) IN ('manager', 'lead', 'team_lead') THEN 'manager'
                    WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'vp', 'director', 'executive') THEN 'executive'
                    WHEN LOWER(role) IN ('it_admin', 'itadmin', 'it', 'tech_admin') THEN 'it_admin'
                    WHEN LOWER(role) IN ('intern', 'internship', 'trainee') THEN 'intern'
                    ELSE 'employee'
                END
                WHERE role IS NOT NULL;
            """))

        # 2. Standardize managers table
        has_mgr_res = await conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='managers'"))
        if has_mgr_res.scalar():
            logger.info("Standardizing managers table roles...")
            await conn.execute(text("""
                UPDATE managers
                SET role = CASE
                    WHEN LOWER(role) IN ('super_admin', 'superadmin') THEN 'super_admin'
                    WHEN LOWER(role) IN ('admin', 'hr', 'hr_admin', 'hradmin') THEN 'hr_admin'
                    WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'executive') THEN 'executive'
                    WHEN LOWER(role) IN ('it_admin', 'itadmin') THEN 'it_admin'
                    ELSE 'manager'
                END
                WHERE role IS NOT NULL;
            """))

        # 3. Standardize users table
        has_users_res = await conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='users'"))
        if has_users_res.scalar():
            logger.info("Standardizing users table roles...")
            if has_enum:
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role DROP DEFAULT"))
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50) USING role::VARCHAR"))

            await conn.execute(text("""
                UPDATE users
                SET role = CASE
                    WHEN LOWER(role) IN ('super_admin', 'superadmin', 'super_administrator') THEN 'super_admin'
                    WHEN LOWER(role) IN ('admin', 'hr', 'hr_admin', 'hradmin', 'hr_manager', 'payroll_admin', 'finance') THEN 'hr_admin'
                    WHEN LOWER(role) IN ('manager', 'lead', 'team_lead') THEN 'manager'
                    WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'vp', 'director', 'executive') THEN 'executive'
                    WHEN LOWER(role) IN ('it_admin', 'itadmin', 'it', 'tech_admin') THEN 'it_admin'
                    WHEN LOWER(role) IN ('intern', 'internship', 'trainee') THEN 'intern'
                    ELSE 'employee'
                END
                WHERE role IS NOT NULL;
            """))

            if has_enum:
                await conn.execute(text("DROP TYPE IF EXISTS user_role CASCADE"))
                await conn.execute(text("CREATE TYPE user_role AS ENUM ('super_admin', 'hr_admin', 'manager', 'employee', 'executive', 'it_admin', 'intern')"))
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role"))
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'::user_role"))
            else:
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'"))

    logger.info("Role standardization migration completed successfully.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate_roles_to_canonical_enum())
