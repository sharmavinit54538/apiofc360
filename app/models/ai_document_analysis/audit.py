"""AI document analysis audit logging database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ai_document_analysis.document import AnalyzedDocument


class AnalysisAuditLog(Base):
    """Full audit log tracking access to document analysis results."""

    __tablename__ = "analysis_audit_logs"
    __table_args__ = (
        Index("ix_analysis_audit_user", "user_id"),
        Index("ix_analysis_audit_doc", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analyzed_documents.id", ondelete="SET NULL"), nullable=True)

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # UPLOAD, CLASSIFY, EXTRACT, ANALYZE, SEARCH, RAG_QA, COMPARE
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User | None] = relationship("User", lazy="select")
    document: Mapped[AnalyzedDocument | None] = relationship("AnalyzedDocument", lazy="select")
