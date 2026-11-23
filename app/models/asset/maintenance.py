"""Asset maintenance records database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from enum import Enum
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, Enum as SQLEnum, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset.asset import Asset


class MaintenanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssetMaintenanceRecord(Base):
    """Maintenance and repair registry log for an asset."""

    __tablename__ = "asset_maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    
    request_date: Mapped[date] = mapped_column(Date, nullable=False, default=func.current_date())
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vendor: Mapped[str] = mapped_column(String(150), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(*[s.value for s in MaintenanceStatus], name="maintenance_status"),
        nullable=False,
        default=MaintenanceStatus.REQUESTED.value
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    asset: Mapped[Asset] = relationship("Asset", back_populates="maintenance_history")
