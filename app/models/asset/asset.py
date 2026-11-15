"""Company hardware asset inventory record database model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Numeric, JSON, text, func, Date
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.mutable import MutableList

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.company import Company
    from app.models.asset.assignment import AssetAssignmentHistory
    from app.models.asset.maintenance import AssetMaintenanceRecord


# Valid asset statuses
ASSET_STATUSES = {
    "available",
    "assigned",
    "under-repair",
    "maintenance",
    "lost",
    "retired",
    "disposed",
    "archived",
}

# Valid status transitions: from_status -> set of allowed to_statuses
VALID_STATUS_TRANSITIONS = {
    "available": {"assigned", "under-repair", "maintenance", "lost", "retired", "disposed", "archived"},
    "assigned": {"available", "under-repair", "maintenance", "lost", "retired", "disposed", "transferred"},
    "under-repair": {"available", "assigned", "lost", "retired", "disposed"},
    "maintenance": {"available", "assigned", "under-repair", "lost", "retired", "disposed"},
    "lost": {"available", "assigned", "retired", "disposed", "recovered"},
    "retired": {"disposed", "archived"},
    "disposed": {"archived"},
    "archived": {},
    "recovered": {"available", "under-repair", "maintenance"},
}


class Asset(Base):
    """Company hardware asset inventory record."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_company_tag", "company_id", "tag", unique=True),
        Index("ix_assets_status", "status"),
        Index("ix_assets_company_id", "company_id"),
        Index("ix_assets_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    timeline: Mapped[list[dict] | None] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True, server_default=text("'[]'")
    )

    # Lost asset tracking
    lost_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_known_holder_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    # Soft deletion
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee | None] = relationship("Employee", back_populates="assets", lazy="select", foreign_keys="Asset.employee_id")
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

    def can_transition_to(self, new_status: str) -> bool:
        """Check if status transition is valid."""
        if self.status not in VALID_STATUS_TRANSITIONS:
            return False
        return new_status in VALID_STATUS_TRANSITIONS[self.status]

    def transition_status(self, new_status: str) -> None:
        """Transition to new status with validation."""
        if not self.can_transition_to(new_status):
            raise ValueError(f"Invalid status transition from '{self.status}' to '{new_status}'")
        self.status = new_status
