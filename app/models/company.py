"""Company / Tenant database model."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import String, DateTime, func, Boolean, Integer, JSON, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Company(Base):
    """Company / Tenant in the Multi-Tenant SaaS platform."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
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
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    onboarding_step: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    company_profile: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    hr_settings: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
