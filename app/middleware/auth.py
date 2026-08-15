"""JWT Authentication Middleware and Dependencies."""

from __future__ import annotations

import logging
from typing import Annotated, Any
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.db.database import get_db_session
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.services.token_service import is_access_token_blacklisted
from app.utils.jwt import decode_token

logger = logging.getLogger(__name__)

# auto_error=False allows inspect of custom headers/formats and graceful logging
security = HTTPBearer(auto_error=False)


async def get_current_user_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    request: Request = None,
) -> dict[str, Any]:
    """Verify bearer access token claims and return payload context."""
    token = None

    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request is not None:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth_header and auth_header.strip().lower().startswith("bearer "):
            token = auth_header.strip().split(" ", 1)[1].strip()

    if not token:
        logger.info("No Authorization Bearer token provided — rejecting request.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Check Redis token blocklist (and legacy fallback)
    if await redis_client.is_token_blacklisted(token) or is_access_token_blacklisted(token):
        logger.warning("Access Token rejected: Token has been blacklisted on logout or revocation.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired login session. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = decode_token(token)
        if claims.get("type") != "access":
            logger.warning("Access Token validation failed: Token type is '%s', expected 'access'.", claims.get("type"))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Expected access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = claims.get("sub")
        role = claims.get("role")
        company_id = claims.get("company_id")
        iat = claims.get("iat", 0)

        # 2. Check user-level stateless revocation (e.g. from password update or admin lock)
        if user_id:
            revoked_before = await redis_client.get_user_revoked_before(user_id)
            if revoked_before is not None and iat <= revoked_before:
                logger.warning(
                    "Access Token rejected: Token iat (%s) <= user revocation timestamp (%s) for user %s",
                    iat, revoked_before, user_id
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired login session. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        logger.debug("Access Token validated | user_id=%s | role=%s", user_id, role)

        from app.db.base import tenant_id_ctx
        if company_id:
            try:
                tenant_id_ctx.set(uuid.UUID(str(company_id)))
            except ValueError:
                pass

        if request is not None:
            request.state.user_claims = claims

        return claims

    except ValueError as exc:
        err_msg = str(exc)
        if "expired" in err_msg.lower():
            logger.warning("Access Token expired: %s", err_msg)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token has expired. Please refresh session.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The access token has expired"'},
            ) from exc
        elif "signature" in err_msg.lower():
            logger.warning("JWT signature invalid: %s", err_msg)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid JWT signature.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The signature is invalid"'},
            ) from exc
        else:
            logger.warning("JWT decoding failed: %s", err_msg)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            ) from exc


async def get_current_user(
    claims: Annotated[dict[str, Any], Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Resolve and return the authenticated User instance from DB, validating both User and employment/management active state."""
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )
    try:
        user_id = uuid.UUID(str(user_id_raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token.",
        )

    repo = AuthRepository(session)
    user = await repo.get_user_by_id(user_id)
    if not user or user.is_deleted:
        logger.warning("User resolution failed: User %s not found in DB or is deleted.", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists.",
        )

    account_status_val = str(getattr(user, "account_status", "") or "").upper()
    if not user.is_active or account_status_val in ("SUSPENDED", "DEACTIVATED", "INACTIVE", "TERMINATED", "EXITED"):
        logger.warning("User resolution rejected: User %s is inactive (account_status=%s).", user_id, account_status_val)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or disabled.",
        )

    # Verify employment / manager active lifecycle state
    from sqlalchemy import select
    from app.models.manager import Manager

    emp_res = await session.execute(
        select(Employee).where(
            Employee.user_id == user_id,
            Employee.is_deleted == False,
        ).execution_options(bypass_tenant=True)
    )
    emp = emp_res.scalar_one_or_none() if hasattr(emp_res, "scalar_one_or_none") and callable(emp_res.scalar_one_or_none) else None
    if isinstance(emp, Employee):
        if (
            not emp.is_active
            or emp.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(emp, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            logger.warning(
                "User resolution rejected: Employee profile for user %s is deactivated/archived/terminated (status=%s, is_active=%s).",
                user_id, emp.status, emp.is_active
            )
            if user.is_active:
                user.is_active = False
                await session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employee profile is inactive, deactivated, or terminated.",
            )

    mgr_res = await session.execute(
        select(Manager).where(
            Manager.user_id == user_id,
            Manager.is_deleted == False,
        ).execution_options(bypass_tenant=True)
    )
    mgr = mgr_res.scalar_one_or_none() if hasattr(mgr_res, "scalar_one_or_none") and callable(mgr_res.scalar_one_or_none) else None
    if isinstance(mgr, Manager):
        if (
            not mgr.is_active
            or mgr.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(mgr, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            logger.warning(
                "User resolution rejected: Manager profile for user %s is deactivated/archived/terminated (status=%s, is_active=%s).",
                user_id, mgr.status, mgr.is_active
            )
            if user.is_active:
                user.is_active = False
                await session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager profile is inactive, deactivated, or terminated.",
            )

    return user


async def get_current_active_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency verifying user is active and verified."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )
    return user


async def get_current_employee(
    claims: Annotated[dict[str, Any], Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Employee:
    """Resolve the employee record associated with the authenticated user and verify active status."""
    user_id = uuid.UUID(str(claims["sub"]))
    from app.repositories.employee_repository import EmployeeRepository
    emp_repo = EmployeeRepository(session)
    emp = await emp_repo.get_by_user_id(user_id)
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found for current user.",
        )
    if (
        not emp.is_active
        or emp.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
        or (getattr(emp, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee profile is inactive, deactivated, or terminated.",
        )
    return emp


async def get_current_company(
    claims: Annotated[dict[str, Any], Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Company:
    """Resolve company associated with current user claims."""
    company_id_raw = claims.get("company_id")
    if not company_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not associated with a company.",
        )
    company_id = uuid.UUID(str(company_id_raw))
    from sqlalchemy import select
    res = await session.execute(select(Company).where(Company.id == company_id))
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found.",
        )
    return company


async def get_current_user_claims_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    request: Request = None,
) -> dict[str, Any] | None:
    """Safely resolve user claims without raising HTTP 401 exceptions if unauthenticated."""
    try:
        return await get_current_user_claims(credentials=credentials, request=request)
    except HTTPException:
        return None
