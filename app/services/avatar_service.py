"""Avatar upload service for OFC360 user profile images.

Reuses the existing LocalStorageProvider from storage_service.py for disk
persistence and the existing static-file mount pattern for public URLs.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.user import User
from app.services.storage_service import LocalStorageProvider

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_AVATAR_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB

ALLOWED_AVATAR_MIME_TYPES: dict[str, str] = {
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

AVATARS_SUBDIR = "avatars"
UPLOAD_ROOT = os.path.abspath(getattr(settings, "UPLOAD_DIR", "uploads"))
AVATARS_DIR = os.path.join(UPLOAD_ROOT, AVATARS_SUBDIR)
os.makedirs(AVATARS_DIR, exist_ok=True)


def _infer_extension(content_type: str) -> str:
    """Return a safe file extension for the given MIME type."""
    ext = ALLOWED_AVATAR_MIME_TYPES.get(content_type)
    if not ext:
        raise AppException(
            message=f"Unsupported image type '{content_type}'. Allowed: {', '.join(sorted(ALLOWED_AVATAR_MIME_TYPES))}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return ext


async def _validate_and_read(file: UploadFile) -> tuple[bytes, str]:
    """Read the upload into memory, validate MIME + magic bytes + size.

    Returns (file_bytes, extension).
    """
    content_type = (file.content_type or "").lower().strip()
    ext = _infer_extension(content_type)

    data = await file.read()

    if not data:
        raise AppException(
            message="Uploaded file is empty.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(data) > MAX_AVATAR_SIZE_BYTES:
        raise AppException(
            message=f"File size exceeds the {MAX_AVATAR_SIZE_BYTES // (1024 * 1024)}MB avatar limit.",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    # Content-level magic-byte validation
    expected_sigs = _IMAGE_SIGNATURES.get(ext, [])
    if expected_sigs:
        valid = any(data.startswith(sig) for sig in expected_sigs)
        # JPEG exif/jfif variants
        if not valid and ext == ".jpg":
            valid = data[:3] == b"\xff\xd8\xff"
        # WebP: first 4 bytes are "RIFF", bytes 8-12 should be "WEBP"
        if not valid and ext == ".webp" and len(data) >= 12:
            valid = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        if not valid:
            raise AppException(
                message="File content does not match the declared image type. Upload a valid JPEG, PNG, or WebP image.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return data, ext


class AvatarService:
    """Handles avatar upload, storage, old-avatar cleanup, and DB persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._provider = LocalStorageProvider(target_dir=AVATARS_DIR)

    async def upload_avatar(self, user: User, file: UploadFile) -> dict[str, Any]:
        """Upload avatar for *user*, persist URL, return response data.

        Workflow:
        1. Validate file (MIME, magic bytes, size).
        2. Write to disk with a unique name.
        3. Build a public URL.
        4. Update user.avatar in DB.
        5. Commit.
        6. Delete old avatar (best-effort, only after commit).
        """
        data, ext = await _validate_and_read(file)

        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = os.path.join(AVATARS_DIR, unique_name)

        # Preserve the old avatar path so we can clean it up *after* the new one succeeds
        old_avatar_url: str | None = user.avatar
        old_avatar_path: str | None = None
        if old_avatar_url and f"/uploads/{AVATARS_SUBDIR}/" in (old_avatar_url or ""):
            old_filename = old_avatar_url.rsplit("/", 1)[-1]
            candidate = os.path.join(AVATARS_DIR, old_filename)
            if os.path.isfile(candidate):
                old_avatar_path = candidate

        # Step 2: write to disk
        try:
            safe_path = self._provider.verify_safe_path(dest_path)
            with open(safe_path, "wb") as f:
                f.write(data)
        except AppException:
            raise
        except Exception as exc:
            logger.error("Avatar disk write failed: %s", exc)
            raise AppException(
                message="Failed to save avatar image. Please try again.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        # Step 3: build public URL (relative, served by StaticFiles mount)
        avatar_url = f"/uploads/{AVATARS_SUBDIR}/{unique_name}"

        # Step 4 & 5: update DB and commit
        try:
            user.avatar = avatar_url
            await self.session.commit()
        except Exception as exc:
            # Roll back: remove the newly written file
            logger.error("DB commit failed after avatar upload: %s", exc)
            try:
                os.remove(safe_path)
            except OSError:
                pass
            await self.session.rollback()
            raise AppException(
                message="Failed to update user profile. Please try again.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        # Step 6: best-effort cleanup of old avatar *after* successful commit
        if old_avatar_path:
            try:
                self._provider.delete_file(old_avatar_path)
                logger.info("Deleted old avatar: %s", old_avatar_path)
            except Exception as cleanup_exc:
                logger.warning("Could not delete old avatar %s: %s", old_avatar_path, cleanup_exc)

        logger.info("Avatar uploaded for user %s → %s", user.id, avatar_url)
        return {"avatar": avatar_url}
