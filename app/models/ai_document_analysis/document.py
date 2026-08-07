"""AnalyzedDocument database model."""

from __future__ import annotations

from sqlalchemy import Index

from app.db.base import Base
from app.models.ai_document_analysis.mixins.file_info import DocumentFileInfoMixin
from app.models.ai_document_analysis.mixins.ai_data import DocumentAIDataMixin
from app.models.ai_document_analysis.mixins.relations import DocumentRelationsMixin


class AnalyzedDocument(
    DocumentFileInfoMixin,
    DocumentAIDataMixin,
    DocumentRelationsMixin,
    Base,
):
    """Stores metadata, classification, raw text, and structured extraction results."""

    __tablename__ = "analyzed_documents"
    __table_args__ = (
        Index("ix_analyzed_docs_checksum", "file_checksum"),
        Index("ix_analyzed_docs_status", "status"),
        Index("ix_analyzed_docs_classification", "classification"),
    )
