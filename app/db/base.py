"""Declarative base metadata and tenant mixin for SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.company import Company

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

import contextvars

tenant_id_ctx = contextvars.ContextVar("tenant_id", default=None)


def new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamp fields."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantMixin:
    """Mixin to add company_id field and company relationship to tenant-isolated models."""
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    # We can dynamically define company relationship in models if needed,
    # or just declare it via standard Mapped[Company | None] relationship on the subclass.
