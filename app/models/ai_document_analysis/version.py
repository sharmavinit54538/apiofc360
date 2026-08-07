"""Document version tracking database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ai_document_analysis.document import AnalyzedDocument


class DocumentAnalysisVersion(Base):
    """Tracks document version history and upload updates."""

    __tablename__ = "document_analysis_versions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analyzed_documents.id", ondelete="CASCADE"), nullable=False)

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    document: Mapped[AnalyzedDocument] = relationship("AnalyzedDocument", back_populates="versions")
    uploader: Mapped[User | None] = relationship("User", lazy="select")
