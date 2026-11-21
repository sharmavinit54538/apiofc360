import logging
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import (
    ValidationException as invalid_token,
    ConflictException as school_suspended,
    ConflictException as tenant_mismatch,
    ForbiddenException as user_inactive,
    ForbiddenException as permission_denied,
)
from app.core.permissions import permission_granted
from app.utils.jwt import decode_token
from app.db.session import get_db
from app.models.school import School
from app.models.user import User

logger = logging.getLogger("ofc360.auth")
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    tenant_id: str
    school_id: str
    role: str
    permissions: list[str]
    email: str
    name: str


async def get_current_user() -> CurrentUser:
    """Retired school identity provider; cannot authenticate HRMS users."""
    from fastapi import HTTPException
    raise HTTPException(410, "The school API is not part of the OFC360 HRMS contract.")


def require_permission(permission: str):
    async def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not permission_granted(current.permissions, permission):
            from app.core.exceptions import ForbiddenException as permission_denied

            raise permission_denied()
        return current

    return _dep


def require_role(*roles: str):
    async def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current.role not in roles:
            from app.core.exceptions import ForbiddenException as permission_denied

            raise permission_denied()
        return current

    return _dep
