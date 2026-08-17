"""Document OCR Repository for database operations on document_ocr_records."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_ocr import DocumentOCRRecord

logger = logging.getLogger(__name__)


class DocumentOCRRepository:
    """Async repository layer for document_ocr_records table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: DocumentOCRRecord) -> DocumentOCRRecord:
        """Insert a new DocumentOCRRecord into database."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_id(
        self,
        document_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
        is_super_admin: bool = False,
    ) -> DocumentOCRRecord | None:
        """Fetch OCR record by UUID with tenant isolation.
        
        Args:
            document_id: The document UUID to fetch
            company_id: The company ID for tenant isolation (required for non-super-admin)
            is_super_admin: If True, bypasses tenant isolation (Super Admin access)
        """
        if not is_super_admin and company_id is None:
            raise ValueError("company_id is required for non-Super Admin access")
        
        stmt = select(DocumentOCRRecord).where(DocumentOCRRecord.id == document_id)
        if not is_super_admin and company_id is not None:
            stmt = stmt.where(DocumentOCRRecord.company_id == company_id)
        # Super Admin bypasses tenant filter
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_records(
        self,
        company_id: uuid.UUID | None = None,
        document_type: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        is_super_admin: bool = False,
    ) -> tuple[Sequence[DocumentOCRRecord], int]:
        """Fetch paginated OCR records with filters and tenant isolation.
        
        Args:
            company_id: The company ID for tenant isolation (required for non-super-admin)
            is_super_admin: If True, bypasses tenant isolation (Super Admin access)
        """
        if not is_super_admin and company_id is None:
            raise ValueError("company_id is required for non-Super Admin access")
        
        stmt = select(DocumentOCRRecord)

        conditions = []
        if not is_super_admin and company_id is not None:
            conditions.append(DocumentOCRRecord.company_id == company_id)
        # Super Admin bypasses tenant filter
        if document_type:
            conditions.append(DocumentOCRRecord.document_type == document_type)
        if status_filter:
            conditions.append(DocumentOCRRecord.status == status_filter)
        if search:
            search_pattern = f"%{search}%"
            conditions.append(
                or_(
                    DocumentOCRRecord.original_filename.ilike(search_pattern),
                    DocumentOCRRecord.extracted_text.ilike(search_pattern),
                )
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        # Query with pagination and order by created_at desc
        stmt = stmt.order_by(DocumentOCRRecord.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        records = res.scalars().all()

        return records, total

    async def update(
        self,
        record: DocumentOCRRecord,
        **updates: dict,
    ) -> DocumentOCRRecord:
        """Update existing record attributes."""
        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(record)
        return record
