"""Secure CLI utility to seed or reset the platform Super Admin account.

Usage:
    python scripts/seed_super_admin.py --password <strong_password>
    # Or set SUPER_ADMIN_PASSWORD env var:
    SUPER_ADMIN_PASSWORD=MyStr0ng!Pass python scripts/seed_super_admin.py
"""

import argparse
import asyncio
import logging
import os
import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.db.database import AsyncSessionLocal
from app.models.user import User, UserRole, UserAccountStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def seed_super_admin(email: str, password: str, name: str, phone: str) -> None:
    """Create or update a platform Super Admin account."""
    clean_email = email.strip().lower()
    if clean_email != "superadmin@ofc360.com":
        raise ValueError("Security Lock Violation: Only 'superadmin@ofc360.com' can be seeded as Super Admin.")

    async with AsyncSessionLocal() as session:
        # Check if user already exists with this email
        res = await session.execute(
            select(User).where(User.email == clean_email).execution_options(bypass_tenant=True)
        )
        user = res.scalars().first()

        password_hash = hash_password(password)

        if user:
            logger.info("Found existing user with email: %s. Upgrading to Super Admin...", clean_email)
            user.role = UserRole.SUPER_ADMIN
            user.name = name
            user.phone = phone
            user.password_hash = password_hash
            user.is_active = True
            user.is_verified = True
            user.account_status = UserAccountStatus.ACTIVE.value
            user.must_change_password = False
            user.company_id = None  # Super Admin is platform-level
            session.add(user)
            await session.commit()
            logger.info("Successfully updated platform Super Admin account: %s", clean_email)
        else:
            logger.info("Creating new platform Super Admin account: %s...", clean_email)
            new_user = User(
                id=uuid.uuid4(),
                company_id=None,  # Platform level
                name=name,
                email=clean_email,
                phone=phone,
                password_hash=password_hash,
                role=UserRole.SUPER_ADMIN,
                account_status=UserAccountStatus.ACTIVE.value,
                is_active=True,
                is_verified=True,
                must_change_password=False,
            )
            session.add(new_user)
            await session.commit()
            logger.info("Successfully created platform Super Admin account: %s (ID: %s)", clean_email, new_user.id)


def main():
    parser = argparse.ArgumentParser(description="Seed platform Super Admin account.")
    parser.add_argument("--email", default="superadmin@ofc360.com", help="Super admin email (must be superadmin@ofc360.com)")
    parser.add_argument("--password", default=None, help="Super admin password (or set SUPER_ADMIN_PASSWORD env var)")
    parser.add_argument("--name", default="Platform Super Admin", help="Super admin full name")
    parser.add_argument("--phone", default="9999999999", help="Super admin phone number")
    args = parser.parse_args()

    password = args.password or os.environ.get("SUPER_ADMIN_PASSWORD", "")
    if not password:
        parser.error("--password is required (or set SUPER_ADMIN_PASSWORD env var)")

    asyncio.run(seed_super_admin(
        email=args.email,
        password=password,
        name=args.name,
        phone=args.phone,
    ))


if __name__ == "__main__":
    main()

