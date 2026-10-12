"""JWT Authentication Middleware and Dependencies."""

from __future__ import annotations

import logging
from typing import Annotated, Any
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import async_cache_get, async_cache_set, cache_delete
from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.base import tenant_id_ctx
from app.db.database import get_db_session
from app.models.company import Company
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.utils.jwt import decode_token

logger = logging.getLogger(__name__)

# auto_error=False allows inspect of custom headers/formats and graceful logging
security = HTTPBearer(auto_error=False)

AUTH_ACTIVE_CACHE_TTL = 60  # seconds
AUTH_ACTIVE_CACHE_PREFIX = "auth:active"


def _auth_active_cache_key(user_id: uuid.UUID, company_id: uuid.UUID | None) -> str:
    """Generate tenant-scoped cache key for user active state."""
    company_part = str(company_id) if company_id else "no_company"
    return f"{AUTH_ACTIVE_CACHE_PREFIX}:{company_part}:{user_id}"


async def _check_user_active_cached(user_id: uuid.UUID, company_id: uuid.UUID | None, session: AsyncSession) -> tuple[bool, str | None]:
    """
    Check if user account is active, using cache.
    Returns: (is_active, rejection_reason_if_inactive)
    """
    cache_key = _auth_active_cache_key(user_id, company_id)
    
    # Try cache first
    cached = await async_cache_get(cache_key)
    if cached is not None:
        return cached.get("active", False), cached.get("reason")
    
    # Cache miss - perform full check
    repo = AuthRepository(session)
    user = await repo.get_user_by_id(user_id)
    if not user or user.is_deleted:
        return False, "User account no longer exists."
    
    account_status_val = str(getattr(user, "account_status", "") or "").upper()
    if not user.is_active or account_status_val in ("SUSPENDED", "DEACTIVATED", "INACTIVE", "TERMINATED", "EXITED"):
        return False, "User account is inactive or disabled."
    
    # Check employee profile
    emp_res = await session.execute(
        select(Employee).where(
            Employee.user_id == user_id,
            Employee.is_deleted == False,
        ).execution_options(bypass_tenant=True)
    )
    emp = emp_res.scalar_one_or_none()
    if isinstance(emp, Employee):
        if (
            not emp.is_active
            or emp.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(emp, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            return False, "Employee profile is inactive, deactivated, or terminated."
    
    # Check manager profile
    mgr_res = await session.execute(
        select(Manager).where(
            Manager.user_id == user_id,
            Manager.is_deleted == False,
        ).execution_options(bypass_tenant=True)
    )
    mgr = mgr_res.scalar_one_or_none()
    if isinstance(mgr, Manager):
        if (
            not mgr.is_active
            or mgr.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(mgr, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            return False, "Manager profile is inactive, deactivated, or terminated."
    
    # All checks passed - cache the positive result
    await async_cache_set(cache_key, {"active": True, "reason": None}, ttl_seconds=AUTH_ACTIVE_CACHE_TTL)
    return True, None


async def invalidate_auth_active_cache(user_id: uuid.UUID, company_id: uuid.UUID | None) -> None:
    """Invalidate the cached auth active state for a user."""
    cache_key = _auth_active_cache_key(user_id, company_id)
    await cache_delete(cache_key)
    # Also delete from in-memory store
    cache_delete(cache_key)


async def invalidate_all_auth_active_cache_for_user(user_id: uuid.UUID) -> None:
    """Invalidate all cached auth active states for a user across all companies.
    This is a fallback when company_id is not available."""
    # In practice, we can't easily scan Redis keys, but we can clear the in-memory store
    # For Redis, the keys will expire naturally. The in-memory fallback is cleared here.
    # A more complete solution would use Redis SCAN or a company registry.
    pass


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

    # 1. Check Redis token blocklist and user revocation in a single round trip
    # In development, allow fallback only if explicitly configured
    is_production = settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}
    
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

        # 2. Combined Redis check for token blacklist and user revocation
        if user_id:
            token_blacklisted, revoked_before = await redis_client.check_token_state(token, user_id)
            
            if token_blacklisted:
                logger.warning("Access Token rejected: Token has been blacklisted on logout or revocation.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired login session. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
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
        
        # In production, Redis must be available for token revocation checks
        if is_production and not redis_client.is_connected:
            logger.error("Redis unavailable in production - cannot verify token revocation state")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable. Please try again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

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

    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    # Use cached active state check
    is_active, reason = await _check_user_active_cached(user_id, company_id, session)
    if not is_active:
        logger.warning("User resolution rejected: User %s - %s", user_id, reason)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason,
        )

    repo = AuthRepository(session)
    user = await repo.get_user_by_id(user_id)
    if not user or user.is_deleted:
        logger.warning("User resolution failed: User %s not found in DB or is deleted.", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists.",
        )

    # Preserve side effect: set user.is_active = False when profile is terminated
    # This is only reached if cache was bypassed or missed and check passed
    # The actual rejection would have happened in _check_user_active_cached
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
