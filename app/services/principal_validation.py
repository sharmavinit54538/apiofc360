"""Validate signed claims against current persisted identity and session state."""
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.user import User
from app.models.user.role import OFFICIAL_SUPER_ADMIN_EMAIL
from app.models.refresh_token import RefreshToken


async def validate_principal(session, claims):
    try:
        actor_id = uuid.UUID(str(claims["sub"]))
        company_id = uuid.UUID(str(claims["company_id"])) if claims.get("company_id") else None
        family_id = uuid.UUID(str(claims["sid"])) if claims.get("sid") else None
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid identity claims.") from exc
    user = await session.scalar(select(User).where(User.id == actor_id).execution_options(bypass_tenant=True))
    if not user or user.is_deleted:
        raise HTTPException(401, "User account no longer exists.")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if user.company_id != company_id or role != claims.get("role"):
        raise HTTPException(401, "Identity changed. Please sign in again.")
    if not user.is_active or not user.is_verified or str(user.account_status).upper() != "ACTIVE":
        raise HTTPException(403, "User account is inactive or unverified.")
    if role == "super_admin" and (user.email != OFFICIAL_SUPER_ADMIN_EMAIL or company_id is not None):
        raise HTTPException(403, "Invalid platform owner identity.")
    if family_id:
        active = await session.scalar(select(RefreshToken.id).where(
            RefreshToken.user_id == actor_id, RefreshToken.family_id == family_id,
            RefreshToken.revoked.is_(False), RefreshToken.expires_at > datetime.now(timezone.utc)).limit(1))
        if not active:
            raise HTTPException(401, "Login session has expired or been revoked.")
    return user
