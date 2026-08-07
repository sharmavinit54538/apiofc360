"""Metadata and onboarding columns mixin for User model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column


class UserMetaColumnsMixin:
    """Metadata audit timestamps and onboarding progression state."""

    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    first_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    onboarding_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
