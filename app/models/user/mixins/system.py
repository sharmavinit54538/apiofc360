"""System status and audit column mixin for User model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user.role import UserRole


class UserSystemColumnsMixin:
    """Core account state, role, and security access fields."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", inherit_schema=True),
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
