"""Document expiry alert tracking database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee_document import EmployeeDocument


class DocumentExpiryTracking(Base):
    """Alert tracker log for expiring employee documents."""

    __tablename__ = "document_expiry_tracking"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_doc_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="CASCADE"), nullable=False)

    days_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee_document: Mapped[EmployeeDocument] = relationship("EmployeeDocument", back_populates="expiry_tracks")
