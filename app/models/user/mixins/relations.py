"""Relationships mixin for User model using declared_attr."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, relationship, declared_attr

if TYPE_CHECKING:
    from app.models.otp import OTP
    from app.models.refresh_token import RefreshToken
    from app.models.company import Company
    from app.models.password_reset import PasswordResetToken


class UserRelationshipsMixin:
    """SQLAlchemy relationships mapped with declared_attr decorators."""

    @declared_attr
    def otps(cls) -> Mapped[list[OTP]]:
        return relationship("OTP", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    @declared_attr
    def refresh_tokens(cls) -> Mapped[list[RefreshToken]]:
        return relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    @declared_attr
    def password_resets(cls) -> Mapped[list[PasswordResetToken]]:
        return relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    @declared_attr
    def company(cls) -> Mapped[Company | None]:
        return relationship("Company", lazy="selectin")
