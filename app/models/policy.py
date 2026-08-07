"""Database models for Enterprise HR Policy AI.

Includes policies registration records and vector semantic chunk tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company


class CompanyPolicyDocument(Base):
    """Company manual document (Leave rules, travel rules, security code)."""

    __tablename__ = "company_policy_documents"
    __table_args__ = (
        Index("ix_policy_documents_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # LEAVE, TRAVEL, IT, SECURITY, PAYROLL, COMPLIANCE
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")
    chunks: Mapped[list[CompanyPolicyChunk]] = relationship("CompanyPolicyChunk", back_populates="document", cascade="all, delete-orphan", lazy="select")


class CompanyPolicyChunk(Base):
    """Divided semantic parts of policy document with calculated nomic-embed-text floats."""

    __tablename__ = "company_policy_chunks"
    __table_args__ = (
        Index("ix_policy_chunks_doc_id", "policy_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company_policy_documents.id", ondelete="CASCADE"), nullable=False)

    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)  # stores list of floats
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    # Relations
    document: Mapped[CompanyPolicyDocument] = relationship("CompanyPolicyDocument", back_populates="chunks")
