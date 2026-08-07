"""Storage Service for safely handling document uploads, validation, and disk storage."""

from __future__ import annotations

import logging
import os
import uuid
from typing import BinaryIO

from fastapi import UploadFile, status

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

# Allowed MIME types & extension map
ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/jpg": [".jpg", ".jpeg"],
    "image/tiff": [".tif", ".tiff"],
}

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class StorageService:
    """Service to validate and store original uploaded files."""

    def __init__(self, target_dir: str | None = None) -> None:
        self.target_dir = target_dir or os.path.join(settings.UPLOAD_DIR, "documents")
        os.makedirs(self.target_dir, exist_ok=True)

    def validate_file(self, file: UploadFile, file_bytes: bytes) -> None:
        """Validate uploaded file format, emptiness, and size limit."""
        if not file_bytes or len(file_bytes) == 0:
            raise AppException(
                message="Uploaded file is empty.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # File size check
        max_size_bytes = settings.DOCUMENT_OCR_MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_size_bytes:
            raise AppException(
                message=f"File size exceeds maximum allowed limit of {settings.DOCUMENT_OCR_MAX_FILE_SIZE_MB}MB.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Extension check
        original_filename = file.filename or "file.pdf"
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message=f"Unsupported file format '{ext}'. Supported formats: PDF, PNG, JPG, JPEG, TIFF.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Mime type validation
        content_type = (file.content_type or "").lower()
        if content_type and content_type not in ALLOWED_MIME_TYPES:
            # Fallback if standard image/pdf extension matches
            if ext not in ALLOWED_EXTENSIONS:
                raise AppException(
                    message=f"Unsupported MIME type '{content_type}'. Allowed: PDF, PNG, JPEG, TIFF.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

    async def save_file(self, file: UploadFile) -> dict:
        """Read, validate, and store file to disk with unique UUID filename."""
        file_bytes = await file.read()
        self.validate_file(file, file_bytes)

        original_filename = os.path.basename(file.filename or "uploaded_document")
        ext = os.path.splitext(original_filename)[1].lower()
        if not ext:
            ext = ".pdf"

        # Unique UUID filename
        unique_id = uuid.uuid4().hex
        stored_filename = f"ocr_{unique_id}{ext}"
        file_path = os.path.join(self.target_dir, stored_filename)

        try:
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            logger.info("Saved file successfully to %s", file_path)
        except Exception as exc:
            logger.exception("Failed to write uploaded file to disk: %s", exc)
            raise AppException(
                message="Failed to save uploaded document to storage.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        content_type = file.content_type or self._infer_mime_type(ext)

        return {
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "file_path": os.path.abspath(file_path),
            "file_bytes": file_bytes,
            "file_size": len(file_bytes),
            "mime_type": content_type,
        }

    def _infer_mime_type(self, ext: str) -> str:
        if ext in [".jpg", ".jpeg"]:
            return "image/jpeg"
        if ext == ".png":
            return "image/png"
        if ext in [".tif", ".tiff"]:
            return "image/tiff"
        return "application/pdf"
