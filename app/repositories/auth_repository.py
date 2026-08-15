"""Authentication and OTP repository for database access."""

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp import OTP
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.models.password_reset import PasswordResetToken


class AuthRepository:
    """Repository for managing User and OTP persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        """Return a user by email, if one exists."""

        if not email:
            return None
        from sqlalchemy import func
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(
                func.lower(User.email) == func.lower(email.strip()),
                (User.is_deleted.is_(False) | User.is_deleted.is_(None))
            )
            .order_by(User.is_active.desc(), User.created_at.desc())
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_user_by_phone(self, phone: str) -> User | None:
        """Return a user by phone number, if one exists."""

        if not phone:
            return None
        trimmed = str(phone).strip()
        import re
        clean_digits = re.sub(r"[\s\-\(\)\.]+", "", trimmed)
        if clean_digits.startswith("+91"):
            clean_digits = clean_digits[3:]
        elif clean_digits.startswith("91") and len(clean_digits) == 12:
            clean_digits = clean_digits[2:]
        elif clean_digits.startswith("0") and len(clean_digits) == 11:
            clean_digits = clean_digits[1:]

        from sqlalchemy import or_
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(
                or_(User.phone == trimmed, User.phone == clean_digits),
                (User.is_deleted.is_(False) | User.is_deleted.is_(None))
            )
            .order_by(User.is_active.desc(), User.created_at.desc())
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_user_by_identifier(self, identifier: str) -> User | None:
        """Locate user by email OR phone number (excluding deleted users)."""

        if not identifier:
            return None
        trimmed = str(identifier).strip()
        from sqlalchemy import func, or_
        from sqlalchemy.orm import selectinload

        clean_digits = trimmed
        if "@" not in trimmed:
            import re
            clean_digits = re.sub(r"[\s\-\(\)\.]+", "", trimmed)
            if clean_digits.startswith("+91"):
                clean_digits = clean_digits[3:]
            elif clean_digits.startswith("91") and len(clean_digits) == 12:
                clean_digits = clean_digits[2:]
            elif clean_digits.startswith("0") and len(clean_digits) == 11:
                clean_digits = clean_digits[1:]

        result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(
                or_(
                    func.lower(User.email) == func.lower(trimmed),
                    User.phone == trimmed,
                    User.phone == clean_digits,
                ),
                (User.is_deleted.is_(False) | User.is_deleted.is_(None))
            )
            .order_by(User.is_active.desc(), User.created_at.desc())
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_user_by_verification_token(self, token: str) -> User | None:
        """Find user by email verification token."""
        if not token:
            return None
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(
                User.email_verification_token == token.strip(),
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def update_user_verification(self, user_id: uuid.UUID) -> None:
        """Update user verification status to active and verified, setting account_status to ACTIVE."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                is_verified=True,
                is_active=True,
                account_status="ACTIVE",
                email_verified_at=datetime.now(timezone.utc),
                email_verification_token=None,
                email_verification_expires_at=None,
            )
        )
        await self.session.flush()

    async def set_user_verification_token(
        self, user_id: uuid.UUID, token: str | None, expires_at: datetime | None
    ) -> None:
        """Set or update email verification token and expiration."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                email_verification_token=token,
                email_verification_expires_at=expires_at,
            )
        )
        await self.session.flush()

    async def update_login_audit(self, user_id: uuid.UUID, ip: str | None, device: str | None) -> None:
        """Log audit details on successful login."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                last_login_at=datetime.now(timezone.utc),
                last_login_ip=ip,
                last_login_device=device,
            )
        )
        await self.session.flush()

    async def update_user_password(self, user_id: uuid.UUID, password_hash: str) -> None:
        """Update password hash for a user."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(password_hash=password_hash)
        )
        await self.session.flush()

    # OTP Operations

    async def create_otp(
        self,
        *,
        user_id: uuid.UUID,
        otp_hash: str,
        purpose: str,
        expires_at: datetime,
    ) -> OTP:
        """Create a new OTP record."""

        otp_record = OTP(
            user_id=user_id,
            otp_hash=otp_hash,
            purpose=purpose,
            expires_at=expires_at,
            attempts=0,
            is_used=False,
        )
        self.session.add(otp_record)
        await self.session.flush()
        return otp_record

    async def get_latest_otp(self, user_id: uuid.UUID, purpose: str) -> OTP | None:
        """Retrieve the most recent unused OTP record for a specific purpose."""

        result = await self.session.execute(
            select(OTP)
            .where(
                OTP.user_id == user_id,
                OTP.purpose == purpose,
                OTP.is_used == False,
            )
            .order_by(OTP.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def increment_otp_attempts(self, otp_id: uuid.UUID) -> int:
        """Increment the failure count for an OTP record and return new count."""

        result = await self.session.execute(select(OTP).where(OTP.id == otp_id))
        otp_record = result.scalar_one()
        otp_record.attempts += 1
        await self.session.flush()
        return otp_record.attempts

    async def mark_otp_used(self, otp_id: uuid.UUID) -> None:
        """Mark an OTP record as used."""

        await self.session.execute(
            update(OTP)
            .where(OTP.id == otp_id)
            .values(is_used=True)
        )
        await self.session.flush()

    async def invalidate_all_user_otps(self, user_id: uuid.UUID, purpose: str) -> None:
        """Invalidate all existing active OTP records for a user and purpose."""

        await self.session.execute(
            update(OTP)
            .where(
                OTP.user_id == user_id,
                OTP.purpose == purpose,
                OTP.is_used == False,
            )
            .values(is_used=True)
        )
        await self.session.flush()

    # Refresh Token Operations

    async def create_refresh_token(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        device: str | None = None,
        ip_address: str | None = None,
        family_id: uuid.UUID | None = None,
        parent_token_hash: str | None = None,
    ) -> RefreshToken:
        """Save a hashed refresh token to the database with family tracking."""

        refresh_token = RefreshToken(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            parent_token_hash=parent_token_hash,
            token_hash=token_hash,
            device=device,
            ip_address=ip_address,
            expires_at=expires_at,
            revoked=False,
        )
        self.session.add(refresh_token)
        await self.session.flush()
        return refresh_token

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Retrieve an active unrevoked refresh token by its SHA-256 hash."""

        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.user))
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_refresh_token_by_hash_raw(self, token_hash: str) -> RefreshToken | None:
        """Retrieve a refresh token by SHA-256 hash regardless of revoked status (for reuse detection)."""

        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.user))
            .where(
                RefreshToken.token_hash == token_hash,
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def revoke_refresh_token(self, token_id: uuid.UUID, reason: str | None = None) -> None:
        """Revoke a specific refresh token with optional reason and timestamp."""

        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked=True, revoked_at=now, revoked_reason=reason)
        )
        await self.session.flush()

    async def revoke_token_family(self, family_id: uuid.UUID, reason: str = "FAMILY_REUSE_DETECTED") -> None:
        """Revoke all tokens in a token family upon compromised token reuse detection."""

        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked == False,
            )
            .values(revoked=True, revoked_at=now, revoked_reason=reason)
        )
        await self.session.flush()

    async def revoke_all_user_refresh_tokens(self, user_id: uuid.UUID, reason: str | None = "USER_SESSION_REVOCATION") -> None:
        """Revoke all refresh tokens for a user (forces logout on all devices)."""

        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,
            )
            .values(revoked=True, revoked_at=now, revoked_reason=reason)
        )
        await self.session.flush()

    # ---------------------------------------------------------------------------
    # Account Management Operations
    # ---------------------------------------------------------------------------

    async def get_user_by_id(self, user_id: uuid.UUID) -> "User | None":
        """Return an active, non-deleted user by primary key."""
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(
                User.id == user_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_user_by_email_excluding(self, email: str, exclude_id: uuid.UUID) -> "User | None":
        """Check for duplicate email, ignoring the requesting user's own record."""

        if not email:
            return None
        from sqlalchemy import func
        result = await self.session.execute(
            select(User).where(
                func.lower(User.email) == func.lower(email.strip()),
                User.id != exclude_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def get_user_by_phone_excluding(self, phone: str, exclude_id: uuid.UUID) -> "User | None":
        """Check for duplicate phone, ignoring the requesting user's own record."""

        if not phone:
            return None
        result = await self.session.execute(
            select(User).where(
                User.phone == phone.strip(),
                User.id != exclude_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def update_user_pending_email(self, user_id: uuid.UUID, pending_email: str) -> None:
        """Store the unverified new email address temporarily during change-email flow."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(pending_email=pending_email)
        )
        await self.session.flush()

    async def update_user_email(self, user_id: uuid.UUID, new_email: str) -> None:
        """Commit the verified new email, clear pending_email, and refresh email_verified_at."""

        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                email=new_email,
                pending_email=None,
                email_verified_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()

    async def update_user_phone(self, user_id: uuid.UUID, phone: str) -> None:
        """Update the user's phone number immediately."""

        await self.session.execute(
            update(User).where(User.id == user_id).values(phone=phone)
        )
        await self.session.flush()

    async def count_email_change_otps(self, user_id: uuid.UUID) -> int:
        """Count total OTP records with purpose='email_change' for this user (used for resend limit)."""

        from sqlalchemy import func as sa_func

        result = await self.session.execute(
            select(sa_func.count()).select_from(OTP).where(
                OTP.user_id == user_id,
                OTP.purpose == "email_change",
            )
        )
        return result.scalar_one() or 0

    async def create_user(
        self,
        *,
        name: str,
        email: str,
        phone: str,
        password_hash: str,
        role: UserRole = UserRole.EMPLOYEE,
        is_active: bool = False,
        is_verified: bool = False,
        account_status: str = "PENDING_EMAIL_VERIFICATION",
        email_verification_token: str | None = None,
        email_verification_expires_at: datetime | None = None,
        created_by: uuid.UUID | None = None,
        must_change_password: bool = True,
        company_id: uuid.UUID | None = None,
    ) -> User:
        """Create a new User record."""

        user = User(
            name=name,
            email=email,
            phone=phone,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            is_verified=is_verified,
            account_status=account_status,
            email_verification_token=email_verification_token,
            email_verification_expires_at=email_verification_expires_at,
            created_by=created_by,
            must_change_password=must_change_password,
            company_id=company_id,
        )
        self.session.add(user)
        await self.session.flush()  # populate id without committing
        return user

    async def update_user_activation(
        self,
        user_id: uuid.UUID,
        *,
        password_hash: str,
        is_active: bool = True,
        is_verified: bool = True,
        must_change_password: bool = False,
    ) -> None:
        """Activate a user account — set password, mark active/verified, clear must_change_password flag."""

        await self.session.execute(
            update(User).where(User.id == user_id).values(
                password_hash=password_hash,
                is_active=is_active,
                is_verified=is_verified,
                must_change_password=must_change_password,
            )
        )
        await self.session.flush()

    async def update_user_must_change_password(self, user_id: uuid.UUID, value: bool) -> None:
        """Set or clear the must_change_password flag on a user."""

        await self.session.execute(
            update(User).where(User.id == user_id).values(must_change_password=value)
        )
        await self.session.flush()

    async def create_password_reset_token(
        self,
        *,
        user_id: uuid.UUID,
        role: str,
        hashed_token: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        """Create a new password reset token entry."""
        token_record = PasswordResetToken(
            user_id=user_id,
            role=role,
            hashed_token=hashed_token,
            expires_at=expires_at,
        )
        self.session.add(token_record)
        await self.session.flush()
        return token_record

    async def get_password_reset_token(self, hashed_token: str) -> PasswordResetToken | None:
        """Retrieve a password reset token by its hash."""
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(PasswordResetToken)
            .options(selectinload(PasswordResetToken.user))
            .where(PasswordResetToken.hashed_token == hashed_token)
            .execution_options(bypass_tenant=True)
        )
        return result.scalars().first()

    async def mark_password_reset_token_used(self, token_id: uuid.UUID) -> None:
        """Mark a password reset token as used."""
        await self.session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(used_at=datetime.now(timezone.utc))
        )
        await self.session.flush()

