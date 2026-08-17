"""System status and audit column mixin for User model."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user.role import UserRole, UserAccountStatus


class UserSystemColumnsMixin:
    """Core account state, role, and security access fields."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            inherit_schema=True,
            values_callable=lambda x: [e.value for e in x],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=UserRole.EMPLOYEE,
        server_default=text("'employee'"),
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_login_device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    @property
    def email_verified(self) -> bool:
        """Alias for is_verified."""
        return bool(self.is_verified)

    @property
    def account_status(self) -> str:
        """Computed account status string based on user state."""
        if getattr(self, "_account_status_override", None) is not None:
            return self._account_status_override
        if getattr(self, "is_deleted", False):
            return "DEACTIVATED"
        if not getattr(self, "is_verified", False):
            return "PENDING_EMAIL_VERIFICATION"
        if not getattr(self, "is_active", False):
            return "SUSPENDED"
        return "ACTIVE"

    @account_status.setter
    def account_status(self, value: str | None) -> None:
        self._account_status_override = value
        if value:
            val_upper = str(value).upper()
            if val_upper == "ACTIVE":
                self.is_active = True
                self.is_verified = True
            elif val_upper in ("SUSPENDED", "DEACTIVATED", "INACTIVE"):
                self.is_active = False
            elif val_upper == "PENDING_EMAIL_VERIFICATION":
                self.is_verified = False

    @property
    def email_verification_token(self) -> str | None:
        return getattr(self, "_email_verification_token", None)

    @email_verification_token.setter
    def email_verification_token(self, value: str | None) -> None:
        self._email_verification_token = value

    @property
    def email_verification_expires_at(self) -> datetime | None:
        return getattr(self, "_email_verification_expires_at", None)

    @email_verification_expires_at.setter
    def email_verification_expires_at(self, value: datetime | None) -> None:
        self._email_verification_expires_at = value

    @property
    def created_by(self) -> uuid.UUID | None:
        return getattr(self, "_created_by", None)

    @created_by.setter
    def created_by(self, value: uuid.UUID | None) -> None:
        self._created_by = value

