import logging
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import invalid_token, school_suspended, tenant_mismatch, user_inactive
from app.core.permissions import permission_granted
from app.core.security import decode_token
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


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_company_id: str | None = Header(default=None, alias="X-Company-ID"),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    token = creds.credentials if creds else None
    if not token:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        else:
            for c_name in ("ofc360_access_token", "access_token", "eduflow_access_token"):
                c_val = request.cookies.get(c_name)
                if c_val and c_val.strip():
                    token = c_val.strip()
                    break

    if not token:
        logger.warning("AUTH_ACCESS_TOKEN_MISSING: No Bearer token or access cookie found on %s", request.url.path)
        raise invalid_token()

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        logger.warning("AUTH_ACCESS_TOKEN_INVALID: Token signature invalid or type is not 'access' on %s", request.url.path)
        raise invalid_token()

    token_tenant_id = str(payload.get("tenant_id"))
    requested_tenant = x_tenant_id or x_company_id
    if requested_tenant and str(requested_tenant).strip().lower() != token_tenant_id.lower():
        logger.warning("AUTH_TENANT_MISMATCH: Requested tenant %s != token tenant %s", requested_tenant, token_tenant_id)
        raise tenant_mismatch()

    user = await db.get(User, payload.get("user_id"))
    if not user or str(user.tenant_id) != token_tenant_id:
        logger.warning("AUTH_TENANT_MISMATCH: User tenant mismatch")
        raise tenant_mismatch()
    if user.status != "active":
        logger.warning("AUTH_USER_INACTIVE: User is inactive (status=%s)", user.status)
        raise user_inactive()

    school = await db.get(School, user.tenant_id)
    if not school or school.status != "active":
        logger.warning("AUTH_SCHOOL_SUSPENDED: School status is not active")
        raise school_suspended()

    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        school_id=user.school_id,
        role=user.role,
        permissions=user.permissions_list(),
        email=user.email,
        name=user.name,
    )


def require_permission(permission: str):
    async def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not permission_granted(current.permissions, permission):
            from app.core.exceptions import permission_denied

            raise permission_denied()
        return current

    return _dep


def require_role(*roles: str):
    async def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current.role not in roles:
            from app.core.exceptions import permission_denied

            raise permission_denied()
        return current

    return _dep
