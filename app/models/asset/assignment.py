"""Asset assignment history database model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset.asset import Asset


class AssetAssignmentHistory(Base):
    """Assignment trail tracking for assets."""

    __tablename__ = "asset_assignment_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    
    employee_name: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    assign_date: Mapped[date] = mapped_column(Date, nullable=False, default=func.current_date())
    expected_return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    asset: Mapped[Asset] = relationship("Asset", back_populates="assignment_history")
