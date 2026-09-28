"""Storage Service for safely handling document uploads, validation, and disk storage."""

from __future__ import annotations

import abc
import asyncio
import hashlib
import logging
import os
import re
import uuid
from typing import Any

from fastapi import UploadFile, status

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

# Allowed MIME types & extension map for Document Management
ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/msword": [".doc"],
    "application/x-zip-compressed": [".docx"],
    "application/zip": [".docx"],
    "application/octet-stream": [".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/jpg": [".jpg", ".jpeg"],
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"}

# File signatures (magic bytes) for strict content validation
FILE_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
}

# Resolve upload root to an absolute path once
UPLOAD_ROOT_ABSOLUTE = os.path.abspath(getattr(settings, "UPLOAD_DIR", "uploads"))
DOCUMENTS_DIR_ABSOLUTE = os.path.abspath(os.path.join(UPLOAD_ROOT_ABSOLUTE, "documents"))
os.makedirs(DOCUMENTS_DIR_ABSOLUTE, exist_ok=True)


class BaseStorageProvider(abc.ABC):
    """Abstract interface for storage backend (e.g. Local Disk, S3-compatible object store).
    
    Note: Local disk storage is not durable across container redeploys or ephemeral instances.
    In multi-instance production environments, an S3 / GCS-compatible provider implementing
    this interface should be plugged in.
    """

    @abc.abstractmethod
    async def save_stream(self, file: UploadFile, unique_filename: str) -> dict[str, Any]:
        """Stream uploaded file to destination, validating size and magic bytes."""
        raise NotImplementedError

    @abc.abstractmethod
    def delete_file(self, file_path: str) -> None:
        """Delete file from storage."""
        raise NotImplementedError

    @abc.abstractmethod
    def verify_safe_path(self, file_path: str) -> str:
        """Verify file path stays within allowed storage root to prevent directory traversal."""
        raise NotImplementedError


class LocalStorageProvider(BaseStorageProvider):
    """Local disk storage implementation with chunk streaming and magic byte validation."""

    def __init__(self, target_dir: str | None = None) -> None:
        self.target_dir = os.path.abspath(target_dir or DOCUMENTS_DIR_ABSOLUTE)

    def verify_safe_path(self, file_path: str) -> str:
        real_path = os.path.realpath(file_path)
        real_target_dir = os.path.realpath(self.target_dir)
        if not real_path.startswith(real_target_dir + os.sep) and real_path != real_target_dir:
            raise AppException(
                message="Access denied: invalid file path traversal attempt.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return real_path

    def delete_file(self, file_path: str | None) -> None:
        if not file_path:
            return
        try:
            safe_path = self.verify_safe_path(file_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
                logger.info("Cleaned up file at %s", safe_path)
        except Exception as exc:
            logger.warning("Could not delete file %s: %s", file_path, exc)

    async def save_stream(self, file: UploadFile, unique_filename: str) -> dict[str, Any]:
        file_path = os.path.join(self.target_dir, unique_filename)
        safe_path = self.verify_safe_path(file_path)

        max_size_bytes = getattr(settings, "MAX_DOCUMENT_FILE_SIZE_BYTES", 10 * 1024 * 1024)
        hasher = hashlib.sha256()
        total_bytes = 0
        first_chunk = True
        chunk_size = 64 * 1024  # 64 KB chunks

        ext = os.path.splitext(unique_filename)[1].lower()
        expected_sigs = FILE_SIGNATURES.get(ext, [])

        try:
            with open(safe_path, "wb") as f:
                while True:
                    res = file.read(chunk_size)
                    if hasattr(res, "__await__") or asyncio.iscoroutine(res):
                        chunk = await res
                    else:
                        chunk = res
                    if not chunk:
                        break

                    if first_chunk:
                        first_chunk = False
                        if len(chunk) == 0:
                            raise AppException(
                                message="Uploaded file is empty.",
                                status_code=status.HTTP_400_BAD_REQUEST,
                            )
                        # Magic byte verification
                        if expected_sigs:
                            valid_sig = any(chunk.startswith(sig) for sig in expected_sigs)
                            # Handle JPEG exif/jfif variants
                            if not valid_sig and ext in [".jpg", ".jpeg"] and (
                                chunk.startswith(b"\xff\xd8\xff\xe0") or chunk.startswith(b"\xff\xd8\xff\xe1")
                            ):
                                valid_sig = True
                            if not valid_sig:
                                raise AppException(
                                    message=f"File signature mismatch for extension '{ext}'. The file content does not match its claimed type.",
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                )

                    total_bytes += len(chunk)
                    if total_bytes > max_size_bytes:
                        raise AppException(
                            message=f"File size exceeds maximum allowed limit of {max_size_bytes // (1024 * 1024)}MB.",
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )

                    hasher.update(chunk)
                    f.write(chunk)

            if total_bytes == 0:
                raise AppException(
                    message="Uploaded file is empty.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            return {
                "file_path": safe_path,
                "file_size": total_bytes,
                "document_hash": hasher.hexdigest(),
            }

        except Exception:
            # Clean up partial file on failure
            if os.path.exists(safe_path):
                try:
                    os.remove(safe_path)
                except OSError:
                    pass
            raise


class StorageService:
    """Unified service for document upload validation, chunk streaming, and secure disk management."""

    def __init__(self, provider: BaseStorageProvider | None = None, target_dir: str | None = None) -> None:
        self.provider = provider or LocalStorageProvider(target_dir=target_dir)

    def sanitize_filename(self, filename: str | None) -> str:
        """Sanitize filename: strip directory traversal, control characters, null bytes, cap length to 255."""
        if not filename:
            return "document.pdf"

        if "\x00" in filename:
            raise AppException(message="Invalid filename: null bytes not allowed.", status_code=status.HTTP_400_BAD_REQUEST)

        # Basename and strip path separators
        clean_name = os.path.basename(filename)
        clean_name = clean_name.replace("/", "").replace("\\", "")
        # Remove non-printable control characters
        clean_name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", clean_name)
        clean_name = clean_name.strip()
        if not clean_name:
            clean_name = "document.pdf"

        # Cap length 255 preserving extension
        if len(clean_name) > 255:
            base, ext = os.path.splitext(clean_name)
            clean_name = base[: 255 - len(ext)] + ext

        return clean_name

    def validate_file_metadata(self, file: UploadFile) -> tuple[str, str]:
        """Validate filename extension and MIME type allowlist. Returns (sanitized_filename, ext)."""
        filename = self.sanitize_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        content_type = (file.content_type or "").lower()
        if content_type and content_type not in ALLOWED_MIME_TYPES:
            raise AppException(
                message=f"Unsupported MIME type '{content_type}'.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return filename, ext

    async def save_file(self, file: UploadFile) -> dict[str, Any]:
        """Validate and stream file to secure storage.
        
        Returns:
            dict with original_filename, stored_filename, file_path, file_size, mime_type, document_hash
        """
        filename, ext = self.validate_file_metadata(file)
        unique_name = f"{uuid.uuid4().hex}{ext}"

        res = await self.provider.save_stream(file, unique_name)
        mime_type = file.content_type or self.infer_mime_type(ext)

        return {
            "original_filename": filename,
            "stored_filename": unique_name,
            "file_path": res["file_path"],
            "file_size": res["file_size"],
            "mime_type": mime_type,
            "document_hash": res["document_hash"],
        }

    def delete_file(self, file_path: str | None) -> None:
        """Safely delete file from storage backend."""
        self.provider.delete_file(file_path)

    def verify_safe_path(self, file_path: str) -> str:
        """Ensure file path is valid and within storage root."""
        return self.provider.verify_safe_path(file_path)

    @staticmethod
    def infer_mime_type(ext: str) -> str:
        ext = ext.lower()
        if ext in [".jpg", ".jpeg"]:
            return "image/jpeg"
        if ext == ".png":
            return "image/png"
        if ext == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if ext == ".doc":
            return "application/msword"
        return "application/pdf"