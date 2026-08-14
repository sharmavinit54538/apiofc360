"""Admin tools utility to create or reset the platform Super Admin account."""

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


async def create_super_admin(email: str, password: str, name: str, phone: str) -> None:
    """Create or update platform Super Admin account."""
    clean_email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(User).where(User.email == clean_email).execution_options(bypass_tenant=True)
        )
        user = res.scalars().first()
        password_hash = hash_password(password)

        if user:
            user.role = UserRole.SUPER_ADMIN
            user.name = name
            user.phone = phone
            user.password_hash = password_hash
            user.is_active = True
            user.is_verified = True
            user.account_status = UserAccountStatus.ACTIVE.value
            user.must_change_password = False
            user.company_id = None
            session.add(user)
            await session.commit()
            logger.info("Super Admin updated: %s", clean_email)
        else:
            new_user = User(
                id=uuid.uuid4(),
                company_id=None,
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
            logger.info("Super Admin created: %s (ID: %s)", clean_email, new_user.id)


def main():
    parser = argparse.ArgumentParser(description="Create platform Super Admin.")
    parser.add_argument("--email", default="superadmin@ofc360.com", help="Email")
    parser.add_argument("--password", default="SuperAdmin@OFC360#2026", help="Password")
    parser.add_argument("--name", default="Platform Super Admin", help="Name")
    parser.add_argument("--phone", default="9999999999", help="Phone")
    args = parser.parse_args()

    asyncio.run(create_super_admin(
        email=args.email,
        password=args.password,
        name=args.name,
        phone=args.phone,
    ))


if __name__ == "__main__":
    main()
