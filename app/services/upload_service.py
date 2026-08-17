"""Upload Service orchestrating storage, Google Document AI OCR, parsing, and database persistence."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import UploadFile, status

from app.core.exceptions import AppException
from app.models.document_ocr import DocumentOCRRecord
from app.repositories.document_ocr_repository import DocumentOCRRepository
from app.schemas.document_ocr import DocumentOCRResponse
from app.services.google_document_ai_service import GoogleDocumentAIService
from app.services.parser_service import ParserService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DocumentUploadService:
    """Orchestration service for document upload & OCR processing pipeline."""

    def __init__(
        self,
        repo: DocumentOCRRepository,
        storage_service: StorageService | None = None,
        doc_ai_service: GoogleDocumentAIService | None = None,
        parser_service: ParserService | None = None,
    ) -> None:
        self.repo = repo
        self.storage_service = storage_service or StorageService()
        self.doc_ai_service = doc_ai_service or GoogleDocumentAIService()
        self.parser_service = parser_service or ParserService()

    async def upload_and_process(
        self,
        file: UploadFile,
        document_type: str = "generic",
        company_id: uuid.UUID | None = None,
        uploaded_by: uuid.UUID | None = None,
    ) -> DocumentOCRResponse:
        """Orchestrates end-to-end file upload, Document AI OCR processing, DB storage, and JSON response formatting."""
        logger.info("Upload started | original_filename=%s | document_type=%s", file.filename, document_type)

        # Step 1: Storage and File Validation
        saved_info = await self.storage_service.save_file(file)
        logger.info("Saved upload to disk | stored_filename=%s | size=%s bytes", saved_info["stored_filename"], saved_info["file_size"])

        # Step 2: Create initial DB record with 'processing' status
        initial_record = DocumentOCRRecord(
            company_id=company_id,
            original_filename=saved_info["original_filename"],
            stored_filename=saved_info["stored_filename"],
            file_path=saved_info["file_path"],
            mime_type=saved_info["mime_type"],
            file_size=saved_info["file_size"],
            document_type=document_type,
            status="processing",
            uploaded_by=uploaded_by,
        )
        record = await self.repo.create(initial_record)
        logger.info("Created initial DocumentOCRRecord in DB | id=%s", record.id)

        # Step 3: Send to Google Document AI Process API
        try:
            logger.info("OCR processing started for document_id=%s", record.id)
            doc_ai_res = await self.doc_ai_service.process_document(
                file_bytes=saved_info["file_bytes"],
                mime_type=saved_info["mime_type"],
            )

            processing_time_ms = doc_ai_res.get("processing_time_ms", 0.0)
            document_obj = doc_ai_res.get("document")

            # Step 4: Parse Document AI raw output into structured JSON
            parsed = self.parser_service.parse_document(document_obj)
            logger.info("OCR completed successfully for document_id=%s | extracted %s chars | %s pages", record.id, len(parsed["text"]), parsed["page_count"])

            # Step 5: Update DB record with completed status and OCR results
            updated_record = await self.repo.update(
                record,
                status="completed",
                extracted_text=parsed["text"],
                confidence=parsed["confidence"],
                page_count=parsed["page_count"],
                processing_time_ms=processing_time_ms,
                entities=parsed["entities"],
                tables=parsed["tables"],
                form_fields=parsed["form_fields"],
                pages=parsed["pages"],
                raw_response=parsed["raw_response"],
                error_message=None,
            )

            # Step 6: Return clean structured JSON response matching requirement #6
            return DocumentOCRResponse(
                document_id=str(updated_record.id),
                status=updated_record.status,
                page_count=updated_record.page_count,
                text=updated_record.extracted_text,
                confidence=updated_record.confidence,
                entities=updated_record.entities or [],
                tables=updated_record.tables or [],
                form_fields=updated_record.form_fields or [],
                pages=updated_record.pages or [],
                created_at=updated_record.created_at,
            )

        except Exception as exc:
            logger.error("OCR processing failed for document_id=%s: %s", record.id, str(exc))
            # Update record to failed status
            await self.repo.update(
                record,
                status="failed",
                error_message=str(exc),
            )
            raise

    async def get_document_details(
        self,
        document_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
        is_super_admin: bool = False,
    ) -> DocumentOCRRecord:
        """Fetch complete document metadata and OCR result."""
        record = await self.repo.get_by_id(document_id, company_id=company_id, is_super_admin=is_super_admin)
        if not record:
            raise AppException(
                message=f"Document '{document_id}' not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return record

    async def list_documents(
        self,
        company_id: uuid.UUID | None = None,
        document_type: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        is_super_admin: bool = False,
    ) -> tuple[list[DocumentOCRRecord], int]:
        """Fetch list of OCR history records."""
        records, total = await self.repo.list_records(
            company_id=company_id,
            document_type=document_type,
            status_filter=status_filter,
            search=search,
            limit=limit,
            offset=offset,
            is_super_admin=is_super_admin,
        )
        return list(records), total
