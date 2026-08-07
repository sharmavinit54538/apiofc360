"""Asset maintenance records database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset.asset import Asset


class AssetMaintenanceRecord(Base):
    """Maintenance and repair registry log for an asset."""

    __tablename__ = "asset_maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    
    request_date: Mapped[date] = mapped_column(Date, nullable=False, default=func.current_date())
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vendor: Mapped[str] = mapped_column(String(150), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    asset: Mapped[Asset] = relationship("Asset", back_populates="maintenance_history")
