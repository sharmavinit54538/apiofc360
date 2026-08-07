"""File metadata and OCR state columns mixin."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class DocumentFileInfoMixin:
    """Basic file metadata and processing state tracker columns."""

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # File Info
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf, jpeg, docx, etc.
    file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 for deduplication

    # OCR & Processing State
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    ocr_engine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
