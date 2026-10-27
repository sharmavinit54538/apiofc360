"""Company logo upload service for OFC360 enterprise multi-tenant platform.

Reuses the existing LocalStorageProvider from storage_service.py for disk
persistence and the existing static-file mount pattern for public URLs (/uploads/logos).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.company import Company
from app.services.storage_service import LocalStorageProvider

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_LOGO_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB

ALLOWED_LOGO_MIME_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# Magic-byte signatures for content-level validation
_IMAGE_SIGNATURES: dict[str, list[bytes]] = {
    ".jpg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".webp": [b"RIFF"],
}

LOGOS_SUBDIR = "logos"
UPLOAD_ROOT = os.path.abspath(getattr(settings, "UPLOAD_DIR", "uploads"))
LOGOS_DIR = os.path.join(UPLOAD_ROOT, LOGOS_SUBDIR)
os.makedirs(LOGOS_DIR, exist_ok=True)


def _infer_extension(content_type: str) -> str:
    """Return a safe file extension for the given MIME type."""
    ext = ALLOWED_LOGO_MIME_TYPES.get(content_type)
    if not ext:
        raise AppException(
            message=f"Unsupported image type '{content_type}'. Allowed: {', '.join(sorted(ALLOWED_LOGO_MIME_TYPES))}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return ext


async def _validate_and_read(file: UploadFile) -> tuple[bytes, str]:
    """Read the upload into memory, validate MIME + magic bytes + size.

    Returns (file_bytes, extension).
    """
    raw_filename = (file.filename or "").lower().strip()
    dangerous_exts = {".exe", ".bat", ".cmd", ".sh", ".py", ".pl", ".php", ".js", ".html", ".htm", ".vbs", ".jar", ".svg"}
    if any(raw_filename.endswith(bad_ext) for bad_ext in dangerous_exts):
        raise AppException(
            message="Executable or script files are strictly forbidden.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    content_type = (file.content_type or "").lower().strip()
    ext = _infer_extension(content_type)

    data = await file.read()

    if not data:
        raise AppException(
            message="Uploaded file is empty.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(data) > MAX_LOGO_SIZE_BYTES:
        raise AppException(
            message=f"File size exceeds the {MAX_LOGO_SIZE_BYTES // (1024 * 1024)}MB logo limit.",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    # Content-level magic-byte validation
    expected_sigs = _IMAGE_SIGNATURES.get(ext, [])
    if expected_sigs:
        valid = any(data.startswith(sig) for sig in expected_sigs)
        if not valid and ext == ".jpg":
            valid = data[:3] == b"\xff\xd8\xff"
        if not valid and ext == ".webp" and len(data) >= 12:
            valid = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        if not valid:
            raise AppException(
                message="File content does not match the declared image type. Upload a valid JPEG, PNG, or WebP image.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return data, ext


class CompanyLogoService:
    """Handles company logo upload, storage, old-logo cleanup, and DB persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._provider = LocalStorageProvider(target_dir=LOGOS_DIR)

    async def upload_company_logo(self, company: Company, file: UploadFile) -> dict[str, Any]:
        """Upload logo for company, persist URL in company_profile, return response data.

        Workflow:
        1. Validate file (MIME, magic bytes, size, security).
        2. Write to disk with a unique name.
        3. Build a public URL.
        4. Update company_profile in DB.
        5. Commit.
        6. Delete old logo (best-effort, only after commit).
        """
        data, ext = await _validate_and_read(file)

        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = os.path.join(LOGOS_DIR, unique_name)

        # Preserve the old logo path so we can clean it up after the new one succeeds
        profile = dict(company.company_profile or {})
        old_logo_url: str | None = profile.get("logo") or profile.get("logo_url") or profile.get("logoUrl")
        old_logo_path: str | None = None
        if old_logo_url and f"/uploads/{LOGOS_SUBDIR}/" in str(old_logo_url):
            old_filename = str(old_logo_url).rsplit("/", 1)[-1]
            candidate = os.path.join(LOGOS_DIR, old_filename)
            if os.path.isfile(candidate):
                old_logo_path = candidate

        # Step 2: write to disk safely
        try:
            safe_path = self._provider.verify_safe_path(dest_path)
            with open(safe_path, "wb") as f:
                f.write(data)
        except AppException:
            raise
        except Exception as exc:
            logger.error("Company logo disk write failed: %s", exc)
            raise AppException(
                message="Failed to save company logo image. Please try again.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        # Step 3: build public URL
        logo_url = f"/uploads/{LOGOS_SUBDIR}/{unique_name}"

        # Step 4 & 5: update DB and commit
        try:
            profile["logo"] = logo_url
            profile["logo_url"] = logo_url
            profile["logoUrl"] = logo_url
            company.company_profile = profile
            flag_modified(company, "company_profile")
            if hasattr(company, "logo"):
                setattr(company, "logo", logo_url)
            if hasattr(company, "logo_url"):
                setattr(company, "logo_url", logo_url)

            await self.session.commit()
            await self.session.refresh(company)
        except Exception as exc:
            await self.session.rollback()
            try:
                if os.path.isfile(dest_path):
                    os.remove(dest_path)
            except OSError:
                pass
            logger.error("Company logo DB commit failed: %s", exc)
            raise AppException(
                message="Failed to update company logo in database. Please try again.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        # Step 6: best-effort cleanup of old logo after successful commit
        if old_logo_path and os.path.isfile(old_logo_path) and old_logo_path != dest_path:
            try:
                self._provider.delete_file(old_logo_path)
                logger.info("Cleaned up old company logo at %s", old_logo_path)
            except Exception as cleanup_exc:
                logger.warning("Could not delete old logo %s: %s", old_logo_path, cleanup_exc)

        logger.info("Company logo uploaded for company %s → %s", company.id, logo_url)
        return {
            "logo": logo_url,
            "logo_url": logo_url,
            "logoUrl": logo_url,
        }
