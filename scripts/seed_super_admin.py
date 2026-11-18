"""Provision or explicitly recover the one platform Super Admin.

An existing owner is never changed by default.  Recovery requires ``--recover``
and an operator identity, and it writes an immutable audit record.
"""

import argparse
import asyncio
import logging
import os
import uuid
import sys
from pathlib import Path

from sqlalchemy import select

# Support the documented ``python scripts/seed_super_admin.py`` invocation.
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.security import hash_password
from app.db.database import AsyncSessionLocal
from app.models.audit_log import create_audit_entry
from app.models.user import User, UserRole, UserAccountStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def seed_super_admin(
    email: str,
    password: str,
    name: str | None,
    phone: str | None,
    operator: str,
    *,
    recover: bool = False,
) -> None:
    """Provision the one platform owner or perform an explicit audited recovery."""
    clean_email = email.strip().lower()
    if clean_email != "superadmin@ofc360.com":
        raise ValueError("Security Lock Violation: only superadmin@ofc360.com may be the platform owner.")
    if not operator.strip():
        raise ValueError("An authorized operator identity is required.")
    if len(password) < 12:
        raise ValueError("A password of at least 12 characters is required.")

    async with AsyncSessionLocal() as session:
        owners = (
            await session.scalars(
                select(User)
                .where(User.role == UserRole.SUPER_ADMIN)
                .with_for_update()
                .execution_options(bypass_tenant=True)
            )
        ).all()
        if len(owners) > 1:
            raise RuntimeError("Platform owner integrity violation: multiple SUPER_ADMIN users require manual remediation.")

        user = await session.scalar(
            select(User)
            .where(User.email == clean_email)
            .with_for_update()
            .execution_options(bypass_tenant=True)
        )

        if owners:
            owner = owners[0]
            if owner.email.lower() != clean_email or owner.company_id is not None:
                raise RuntimeError("Platform owner identity is invalid and requires manual remediation.")
            if not recover:
                raise RuntimeError("Platform owner already exists. Use --recover for explicitly authorized recovery.")
            if user is not owner:
                raise RuntimeError("Platform owner record is inconsistent and requires manual remediation.")

            owner.password_hash = hash_password(password)
            owner.is_active = True
            owner.is_verified = True
            owner.account_status = UserAccountStatus.ACTIVE.value
            owner.must_change_password = True
            session.add(
                create_audit_entry(
                    action="PLATFORM_OWNER_RECOVERED",
                    company_id=None,
                    user_id=owner.id,
                    email=clean_email,
                    actor_id=operator.strip(),
                    entity_type="user",
                    entity_id=str(owner.id),
                    details="Explicit CLI recovery reset the platform owner credentials.",
                )
            )
            await session.commit()
            logger.info("Recovered platform owner credentials for %s", clean_email)
            return

        if user is not None:
            raise RuntimeError("The official platform-owner email is assigned to a non-owner account; manual remediation is required.")
        if not name or not name.strip() or not phone or not phone.strip():
            raise ValueError("Initial provisioning requires non-empty --name and --phone values.")

        owner = User(
            id=uuid.uuid4(),
            company_id=None,
            name=name.strip(),
            email=clean_email,
            phone=phone.strip(),
            password_hash=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
            is_verified=True,
            must_change_password=True,
        )
        session.add(owner)
        session.add(
            create_audit_entry(
                action="PLATFORM_OWNER_PROVISIONED",
                company_id=None,
                user_id=owner.id,
                email=clean_email,
                actor_id=operator.strip(),
                entity_type="user",
                entity_id=str(owner.id),
                details="Platform owner was provisioned through the authorized CLI.",
            )
        )
        await session.commit()
        logger.info("Provisioned platform owner account: %s (ID: %s)", clean_email, owner.id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or explicitly recover the platform Super Admin account.")
    parser.add_argument("--email", default="superadmin@ofc360.com", help="Super admin email (must be superadmin@ofc360.com)")
    parser.add_argument("--password", default=None, help="Super admin password (or set SUPER_ADMIN_PASSWORD env var)")
    parser.add_argument("--name", default=None, help="Full name, required for initial provisioning")
    parser.add_argument("--phone", default=None, help="Phone number, required for initial provisioning")
    parser.add_argument("--operator", required=True, help="Authorized operator identity for the audit record")
    parser.add_argument("--recover", action="store_true", help="Explicitly reset an existing platform owner")
    args = parser.parse_args()

    password = args.password or os.environ.get("SUPER_ADMIN_PASSWORD", "")
    if not password:
        parser.error("--password is required (or set SUPER_ADMIN_PASSWORD env var)")

    asyncio.run(seed_super_admin(
        email=args.email,
        password=password,
        name=args.name,
        phone=args.phone,
        operator=args.operator,
        recover=args.recover,
    ))


if __name__ == "__main__":
    main()

