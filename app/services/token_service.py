"""Token service layer managing JWT access and refresh token lifecycles."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.repositories.auth_repository import AuthRepository
from app.utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)

logger = logging.getLogger(__name__)

# Simple in-memory blacklist with throttled auto-pruning of expired tokens
_blacklisted_access_tokens: dict[str, int] = {}  # token_string -> exp_timestamp
_last_prune_time: float = 0.0
_PRUNE_INTERVAL: float = 60.0  # seconds between prune cycles


def _prune_expired_tokens() -> None:
    """Remove expired tokens from blacklist (called at most once per _PRUNE_INTERVAL)."""
    import time
    global _last_prune_time
    now = time.monotonic()
    if now - _last_prune_time < _PRUNE_INTERVAL:
        return
    _last_prune_time = now
    ts_now = int(datetime.now(timezone.utc).timestamp())
    expired = [t for t, ex in _blacklisted_access_tokens.items() if ex < ts_now]
    for t in expired:
        _blacklisted_access_tokens.pop(t, None)


def blacklist_access_token(token: str, exp: int) -> None:
    """Add an access token to the in-memory blacklist until it naturally expires."""
    _blacklisted_access_tokens[token] = exp
    _prune_expired_tokens()


def is_access_token_blacklisted(token: str) -> bool:
    """Return True if the access token has been blacklisted on logout."""
    if token not in _blacklisted_access_tokens:
        return False
    # Check if it has expired (fast path)
    now = int(datetime.now(timezone.utc).timestamp())
    exp = _blacklisted_access_tokens.get(token, 0)
    if exp < now:
        _blacklisted_access_tokens.pop(token, None)
        return False
    _prune_expired_tokens()
    return True


class TokenService:
    """Service handling token generation, validation, rotation, and revocation."""

    def __init__(self, *, session: AsyncSession, auth_repository: AuthRepository) -> None:
        self.session = session
        self.auth_repository = auth_repository

    async def generate_auth_tokens(
        self,
        *,
        user_id: uuid.UUID,
        role: str,
        company_id: uuid.UUID | None = None,
        email: str | None = None,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[str, str, int]:
        """Issue access + refresh token package and save the refresh token hash."""
        from app.core.config import settings

        access_token = create_access_token(user_id=user_id, role=role, company_id=company_id, email=email)
        refresh_token = create_refresh_token(user_id=user_id)
        
        # Save refresh token hash to database
        token_hash = hash_token(refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await self.auth_repository.create_refresh_token(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device=device,
            ip_address=ip_address,
        )
        
        logger.info("New Access Token issued for user: %s", user_id)
        return access_token, refresh_token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    async def rotate_refresh_token(
        self,
        *,
        refresh_token: str,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[str, str, int]:
        """Rotate old refresh token for a new set of access/refresh tokens."""

        try:
            claims = decode_token(refresh_token)
            if claims.get("type") != "refresh":
                raise ValueError("Invalid token type.")
        except Exception as exc:
            err_msg = str(exc)
            if "expired" in err_msg.lower():
                logger.warning("Refresh Token expired during decode: %s", err_msg)
            elif "signature" in err_msg.lower():
                logger.warning("JWT signature invalid: %s", err_msg)
            else:
                logger.warning("JWT decoding failed: %s", err_msg)
            raise AppException(
                message="Invalid or expired refresh token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ) from exc

        # Locate active token record
        token_hash = hash_token(refresh_token)
        token_record = await self.auth_repository.get_refresh_token_by_hash(token_hash)
        
        now = datetime.now(timezone.utc)
        if not token_record:
            logger.info("Token rotation rejected: token not found or already revoked")
            raise AppException(
                message="Invalid or expired refresh token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Force tzinfo in database datetime objects defensively
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            logger.warning("Refresh Token expired: token record expired at %s", expires_at)
            # Revoke it just in case
            await self.auth_repository.revoke_refresh_token(token_record.id)
            await self.session.commit()
            raise AppException(
                message="Invalid or expired refresh token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Retrieve user details
        user = token_record.user
        if not user or user.is_deleted or not user.is_active:
            logger.info("Token rotation rejected: user is deleted or inactive")
            raise AppException(
                message="Invalid or expired refresh token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        logger.info("Refresh Token valid for user: %s", user.id)

        # Revoke the old refresh token (rotation policy)
        await self.auth_repository.revoke_refresh_token(token_record.id)

        # Generate a new pair
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        new_access_token, new_refresh_token, expires_in = await self.generate_auth_tokens(
            user_id=user.id,
            role=role_str,
            company_id=user.company_id,
            email=user.email,
            ip_address=ip_address,
            device=device,
        )
        await self.session.commit()
        return new_access_token, new_refresh_token, expires_in

    async def revoke_refresh_token(self, refresh_token: str) -> None:
        """Revoke a refresh token by hashing it and setting revoked=True in DB."""

        token_hash = hash_token(refresh_token)
        token_record = await self.auth_repository.get_refresh_token_by_hash(token_hash)
        if token_record:
            await self.auth_repository.revoke_refresh_token(token_record.id)


async def get_token_service(session: AsyncSession = Depends(get_db_session)) -> TokenService:
    """Dependency provider for TokenService."""

    return TokenService(session=session, auth_repository=AuthRepository(session))
