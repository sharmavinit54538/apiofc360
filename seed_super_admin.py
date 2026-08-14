"""Secure CLI utility to seed or reset the platform Super Admin account.

Usage:
    python seed_super_admin.py [--email admin@ofc360.com] [--password YourPassword@123] [--name "Platform Super Admin"] [--phone 9999999999]
"""

import argparse
import asyncio
import logging
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
    parser.add_argument("--email", default="superadmin@ofc360.com", help="Super admin email")
    parser.add_argument("--password", default="SuperAdmin@OFC360#2026", help="Super admin password")
    parser.add_argument("--name", default="Platform Super Admin", help="Super admin full name")
    parser.add_argument("--phone", default="9999999999", help="Super admin phone number")
    args = parser.parse_args()

    asyncio.run(seed_super_admin(
        email=args.email,
        password=args.password,
        name=args.name,
        phone=args.phone,
    ))


if __name__ == "__main__":
    main()
