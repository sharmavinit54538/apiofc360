"""Asset request database model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from enum import Enum
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, Enum as SQLEnum, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset.asset import Asset
    from app.models.employee import Employee


class AssetRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AssetRequestType(str, Enum):
    NEW_ASSET = "NEW_ASSET"
    REPLACEMENT = "REPLACEMENT"
    PERIPHERAL = "PERIPHERAL"
    UPGRADE = "UPGRADE"
    ACCESSORY = "ACCESSORY"


class AssetRequest(Base):
    """Employee asset request with approval workflow."""

    __tablename__ = "asset_requests"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )

    request_type: Mapped[str] = mapped_column(
        SQLEnum(*[t.value for t in AssetRequestType], name="asset_request_type"),
        nullable=False
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferred_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(
        SQLEnum(*[s.value for s in AssetRequestStatus], name="asset_request_status"),
        nullable=False,
        default=AssetRequestStatus.PENDING.value
    )

    # Approval fields
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fulfillment fields
    assigned_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", foreign_keys=[employee_id], lazy="select")
    approver: Mapped[Employee | None] = relationship("Employee", foreign_keys=[approver_id], lazy="select")
    assigned_asset: Mapped[Asset | None] = relationship("Asset", foreign_keys=[assigned_asset_id], lazy="select")


class AssetDamageReport(Base):
    """Asset damage report for maintenance tracking."""

    __tablename__ = "asset_damage_reports"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reported_by_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )

    damage_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PHYSICAL, LIQUID, SCREEN, BATTERY, OTHER
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # MINOR, MAJOR, CRITICAL
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_of_incident: Mapped[str | None] = mapped_column(String(200), nullable=True)
    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REPORTED")  # REPORTED, UNDER_REVIEW, MAINTENANCE_SCHEDULED, REPAIRED, REPLACED, CLOSED
    
    # Resolution
    maintenance_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("asset_maintenance_records.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    asset: Mapped[Asset] = relationship("Asset", lazy="select")
    reported_by: Mapped[Employee] = relationship("Employee", foreign_keys=[reported_by_id], lazy="select")
    maintenance_record: Mapped[AssetMaintenanceRecord | None] = relationship("AssetMaintenanceRecord", foreign_keys=[maintenance_record_id], lazy="select")