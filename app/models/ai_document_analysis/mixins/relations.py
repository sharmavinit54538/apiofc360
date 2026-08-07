"""Relationships mixin for AnalyzedDocument model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, relationship, declared_attr

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.ai_document_analysis.version import DocumentAnalysisVersion


class DocumentRelationsMixin:
    """SQLAlchemy relationships mapped to uploader and versions."""

    @declared_attr
    def uploader(cls) -> Mapped[User | None]:
        return relationship("User", lazy="select")

    @declared_attr
    def versions(cls) -> Mapped[list[DocumentAnalysisVersion]]:
        return relationship("DocumentAnalysisVersion", back_populates="document", cascade="all, delete-orphan", lazy="select")
