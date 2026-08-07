"""Company hardware asset inventory record database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Numeric, JSON, text, func, Date
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.asset.assignment import AssetAssignmentHistory
    from app.models.asset.maintenance import AssetMaintenanceRecord


class Asset(Base):
    """Company hardware asset inventory record."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_tag", "tag", unique=True),
        Index("ix_assets_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="laptop")
    serial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="available", server_default=text("'available'"))
    
    # Active assignment
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    next_maintenance: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timeline: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, server_default=text("'[]'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee | None] = relationship("Employee", back_populates="assets", lazy="select")
    assignment_history: Mapped[list[AssetAssignmentHistory]] = relationship(
        "AssetAssignmentHistory",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="desc(AssetAssignmentHistory.assign_date)",
        lazy="select",
    )
    maintenance_history: Mapped[list[AssetMaintenanceRecord]] = relationship(
        "AssetMaintenanceRecord",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="desc(AssetMaintenanceRecord.request_date)",
        lazy="select",
    )
