"""User MFA database model for TOTP Multi-Factor Authentication."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional, List
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, JSON, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.company import Company


class UserMFA(Base):
    """User Multi-Factor Authentication record."""

    __tablename__ = "user_mfa"
    __table_args__ = (
        Index("ix_user_mfa_user_id", "user_id", unique=True),
        Index("ix_user_mfa_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    mfa_secret: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="totp",
        server_default=text("'totp'"),
    )
    backup_codes: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="joined")
    company: Mapped[Company | None] = relationship("Company", foreign_keys=[company_id], lazy="joined")
