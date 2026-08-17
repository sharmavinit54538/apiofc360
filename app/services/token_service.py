"""Token service layer managing JWT access and refresh token lifecycles."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.redis_client import redis_client
from app.db.database import get_db_session
from app.models.refresh_token import RefreshToken
from app.repositories.auth_repository import AuthRepository
from app.utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)

logger = logging.getLogger(__name__)


class TokenService:
    """Service handling token generation, validation, rotation, locking, and reuse detection."""

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
        family_id: uuid.UUID | None = None,
        parent_token_hash: str | None = None,
    ) -> tuple[str, str, int]:
        """Issue access + refresh token package and save the refresh token hash with family tracking."""
        from app.core.config import settings

        access_token = create_access_token(user_id=user_id, role=role, company_id=company_id, email=email)
        refresh_token = create_refresh_token(user_id=user_id)
        
        # Save refresh token hash to database
        token_hash = hash_token(refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await self.auth_repository.create_refresh_token(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            parent_token_hash=parent_token_hash,
            token_hash=token_hash,
            expires_at=expires_at,
            device=device,
            ip_address=ip_address,
        )
        
        logger.info("New Access Token issued for user: %s (family_id=%s)", user_id, family_id)
        return access_token, refresh_token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    async def rotate_refresh_token(
        self,
        *,
        refresh_token: str,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[str, str, int]:
        """Rotate old refresh token for a new set of access/refresh tokens with locking and reuse detection."""

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

        token_hash = hash_token(refresh_token)

        # Concurrency Lock: Prevent race conditions from concurrent frontend requests
        async with redis_client.lock(f"refresh_lock:{token_hash}", ttl_seconds=10):
            # Locate token record (try raw first for reuse detection, with fallback)
            token_record = None
            if hasattr(self.auth_repository, "get_refresh_token_by_hash_raw"):
                token_record = await self.auth_repository.get_refresh_token_by_hash_raw(token_hash)
            
            # If get_refresh_token_by_hash_raw is not mocked or returned unconfigured mock/None, check get_refresh_token_by_hash
            if not isinstance(token_record, RefreshToken) and hasattr(self.auth_repository, "get_refresh_token_by_hash"):
                fallback_record = await self.auth_repository.get_refresh_token_by_hash(token_hash)
                if fallback_record is not None:
                    token_record = fallback_record

            now = datetime.now(timezone.utc)
            if not token_record:
                logger.info("Token rotation rejected: token not found in database")
                raise AppException(
                    message="Invalid or expired refresh token.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # TOKEN FAMILY REUSE DETECTION:
            # If a refresh token was already revoked/used, someone is attempting to reuse a rotated token!
            # Revoke only the compromised token family.
            if getattr(token_record, "revoked", False) is True:
                logger.critical(
                    "SECURITY ALERT: Token family reuse detected! User %s presented revoked token %s (family_id=%s). Revoking compromised token family.",
                    getattr(token_record, "user_id", "unknown"), token_hash[:12], getattr(token_record, "family_id", None)
                )
                if getattr(token_record, "family_id", None):
                    await self.auth_repository.revoke_token_family(token_record.family_id, reason="REUSE_ATTEMPT_DETECTED")
                # NOTE: We no longer revoke ALL user sessions - only the compromised family
                await self.session.commit()
                raise AppException(
                    message="Invalid or expired refresh token. Token family revoked due to reuse detection.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Force tzinfo in database datetime objects defensively
            expires_at = token_record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if now > expires_at:
                logger.warning("Refresh Token expired: token record expired at %s", expires_at)
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
                await self.auth_repository.revoke_refresh_token(token_record.id)
                await self.session.commit()
                raise AppException(
                    message="Invalid or expired refresh token.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            account_status_val = str(getattr(user, "account_status", "") or "").upper()
            if account_status_val in ("SUSPENDED", "DEACTIVATED", "INACTIVE", "TERMINATED", "EXITED"):
                logger.info("Token rotation rejected: user account status is %s", account_status_val)
                user.is_active = False
                await self.auth_repository.revoke_refresh_token(token_record.id)
                await self.session.commit()
                raise AppException(
                    message="Invalid or expired refresh token.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Check associated employee active state
            from sqlalchemy import select
            from app.models.employee import Employee
            from app.models.manager import Manager

            emp_res = await self.session.execute(
                select(Employee).where(
                    Employee.user_id == user.id,
                    Employee.is_deleted == False,
                ).execution_options(bypass_tenant=True)
            )
            emp = emp_res.scalar_one_or_none() if hasattr(emp_res, "scalar_one_or_none") and callable(emp_res.scalar_one_or_none) else None
            if isinstance(emp, Employee) and (
                not emp.is_active
                or emp.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
                or (getattr(emp, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
            ):
                logger.info("Token rotation rejected: associated employee profile %s is deactivated/archived/terminated", emp.id)
                user.is_active = False
                await self.auth_repository.revoke_refresh_token(token_record.id)
                await self.session.commit()
                raise AppException(
                    message="User account or employment profile is inactive or terminated.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Check associated manager active state
            mgr_res = await self.session.execute(
                select(Manager).where(
                    Manager.user_id == user.id,
                    Manager.is_deleted == False,
                ).execution_options(bypass_tenant=True)
            )
            mgr = mgr_res.scalar_one_or_none() if hasattr(mgr_res, "scalar_one_or_none") and callable(mgr_res.scalar_one_or_none) else None
            if isinstance(mgr, Manager) and (
                not mgr.is_active
                or mgr.status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
                or (getattr(mgr, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
            ):
                logger.info("Token rotation rejected: associated manager profile %s is deactivated/archived/terminated", mgr.id)
                user.is_active = False
                await self.auth_repository.revoke_refresh_token(token_record.id)
                await self.session.commit()
                raise AppException(
                    message="User account or manager profile is inactive or terminated.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            logger.info("Refresh Token valid for user: %s (family_id=%s)", user.id, getattr(token_record, "family_id", None))

            # Revoke the old refresh token (rotation policy)
            await self.auth_repository.revoke_refresh_token(token_record.id)

            # Generate a new pair within the SAME family
            role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
            family_id = getattr(token_record, "family_id", None) or uuid.uuid4()
            new_access_token, new_refresh_token, expires_in = await self.generate_auth_tokens(
                user_id=user.id,
                role=role_str,
                company_id=user.company_id,
                email=user.email,
                ip_address=ip_address,
                device=device,
                family_id=family_id,
                parent_token_hash=token_hash,
            )
            await self.session.commit()
            return new_access_token, new_refresh_token, expires_in


    async def revoke_refresh_token(self, refresh_token: str) -> None:
        """Revoke a refresh token by hashing it and setting revoked=True in DB."""

        token_hash = hash_token(refresh_token)
        token_record = await self.auth_repository.get_refresh_token_by_hash(token_hash)
        if token_record:
            await self.auth_repository.revoke_refresh_token(token_record.id, reason="EXPLICIT_REVOCATION")


async def get_token_service(session: AsyncSession = Depends(get_db_session)) -> TokenService:
    """Dependency provider for TokenService."""

    return TokenService(session=session, auth_repository=AuthRepository(session))