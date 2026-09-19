"""Database model for company office geofence locations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company


class OfficeLocation(Base):
    """Designated office physical geofence location boundary."""

    __tablename__ = "office_locations"
    __table_args__ = (
        Index("ix_office_locations_company_id", "company_id"),
        Index("ix_office_locations_branch", "branch"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    branch: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    radius_meters: Mapped[float] = mapped_column(nullable=False, default=200.0, server_default=text("200.0"))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    company: Mapped[Company] = relationship("Company", lazy="select")
