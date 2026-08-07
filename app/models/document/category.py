"""Document category database model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentCategory(Base):
    """Document Categories (e.g. HR Policy, Resume, Visa etc.)."""

    __tablename__ = "document_categories"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_company: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
