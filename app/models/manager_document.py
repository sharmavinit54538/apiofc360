"""ManagerDocument model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.manager import Manager


class ManagerDocument(Base):
    """Government-issued documents for a manager (Aadhaar, PAN, Passport)."""

    __tablename__ = "manager_documents"
    __table_args__ = (Index("ix_manager_documents_manager_id", "manager_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("managers.id", ondelete="CASCADE"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)  # AADHAAR/PAN/PASSPORT
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    manager: Mapped[Manager] = relationship("Manager", back_populates="documents")
