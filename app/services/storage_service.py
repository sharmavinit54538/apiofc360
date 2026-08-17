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

# File signatures (magic bytes) for content validation
FILE_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".tif": [b"II*\x00", b"MM\x00*"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
}


class StorageService:
    """Service to validate and store original uploaded files."""

    def __init__(self, target_dir: str | None = None) -> None:
        # Use a dedicated upload directory outside web-accessible paths
        self.target_dir = target_dir or os.path.join(settings.UPLOAD_DIR, "documents")
        os.makedirs(self.target_dir, exist_ok=True)

    def validate_file(self, file: UploadFile, file_bytes: bytes) -> None:
        """Validate uploaded file format, emptiness, size limit, and content."""
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

        # Null-byte check in filename
        original_filename = file.filename or "file.pdf"
        if "\x00" in original_filename:
            raise AppException(
                message="Invalid filename: null bytes not allowed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Sanitize filename - remove path traversal attempts
        original_filename = os.path.basename(original_filename)
        # Remove any remaining path separators
        original_filename = original_filename.replace("/", "").replace("\\", "")

        # Extension check
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message=f"Unsupported file format '{ext}'. Supported formats: PDF, PNG, JPG, JPEG, TIFF.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Mime type validation
        content_type = (file.content_type or "").lower()
        if content_type and content_type not in ALLOWED_MIME_TYPES:
            raise AppException(
                message=f"Unsupported MIME type '{content_type}'. Allowed: PDF, PNG, JPEG, TIFF.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # File signature (magic bytes) validation
        self._validate_file_signature(file_bytes, ext)

    def _validate_file_signature(self, file_bytes: bytes, ext: str) -> None:
        """Validate file content matches expected file signature for the extension."""
        expected_signatures = FILE_SIGNATURES.get(ext, [])
        if not expected_signatures:
            # Unknown extension - this shouldn't happen due to earlier check
            return

        file_header = file_bytes[:8]  # Read first 8 bytes
        for signature in expected_signatures:
            if file_header.startswith(signature):
                return  # Valid signature found

        # For JPEG, also check for Exif header
        if ext in [".jpg", ".jpeg"] and file_header.startswith(b"\xff\xd8\xff\xe0"):
            return
        if ext in [".jpg", ".jpeg"] and file_header.startswith(b"\xff\xd8\xff\xe1"):
            return

        raise AppException(
            message=f"File content does not match expected format for '{ext}'. File may be corrupted or mislabeled.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    async def save_file(self, file: UploadFile) -> dict:
        """Read, validate, and store file to disk with unique UUID filename."""
        file_bytes = await file.read()
        self.validate_file(file, file_bytes)

        original_filename = file.filename or "uploaded_document"
        # Sanitize the original filename for logging/metadata only
        original_filename = os.path.basename(original_filename)
        original_filename = original_filename.replace("/", "").replace("\\", "")
        original_filename = original_filename.replace("\x00", "")

        ext = os.path.splitext(original_filename)[1].lower()
        if not ext or ext not in ALLOWED_EXTENSIONS:
            ext = ".pdf"

        # Unique UUID filename - never use user-supplied filename for storage
        unique_id = uuid.uuid4().hex
        stored_filename = f"doc_{unique_id}{ext}"
        file_path = os.path.join(self.target_dir, stored_filename)

        # Ensure the path stays within target directory (defense in depth)
        file_path = os.path.normpath(file_path)
        target_dir_norm = os.path.normpath(self.target_dir)
        if not file_path.startswith(target_dir_norm):
            raise AppException(
                message="Invalid file path detected.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

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