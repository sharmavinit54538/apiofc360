"""Platform ownership validation has no account activation side effects."""
from sqlalchemy import select
from app.models.user import User, UserRole
from app.models.user.role import OFFICIAL_SUPER_ADMIN_EMAIL


async def validate_platform_owner(session):
    owners = (await session.scalars(select(User).where(
        User.role == UserRole.SUPER_ADMIN).execution_options(bypass_tenant=True))).all()
    if len(owners) != 1:
        raise RuntimeError("Exactly one platform owner must be provisioned with the operator CLI.")
    owner = owners[0]
    if owner.email.lower() != OFFICIAL_SUPER_ADMIN_EMAIL or owner.company_id is not None:
        raise RuntimeError("Platform owner identity requires operator remediation.")
    # Suspended and deleted states deliberately remain unchanged.
    return owner
