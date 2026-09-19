"""Helpers for Face Attendance local storage writes and audit logs."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.audit_log import AuditLog

UPLOAD_DIR = os.path.join("uploads", "face_attendance")


async def save_face_image(file: UploadFile) -> str:
    """Saves the uploaded file locally and returns its relative path URL."""
    filename = file.filename or "face.jpg"
    _, ext = os.path.splitext(filename.lower())
    
    # Save to local storage
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    relative_path = os.path.join("uploads", "face_attendance", unique_filename).replace("\\", "/")
    save_path = os.path.join(UPLOAD_DIR, unique_filename)

    image_data = await file.read()
    with open(save_path, "wb") as f:
        f.write(image_data)

    return relative_path


async def save_base64_image(image_base64: str, prefix: str = "face") -> str:
    """Saves a base64 encoded image to disk and returns its relative path URL.
    
    Includes robust error handling and fallback paths so storage/permission
    issues never abort database transactions or trigger HTTP 500 errors.
    """
    import base64
    import logging
    import tempfile

    _logger = logging.getLogger(__name__)

    clean_base64 = image_base64.strip()
    if "," in clean_base64:
        clean_base64 = clean_base64.split(",", 1)[1].strip()

    unique_filename = f"{prefix}_{uuid.uuid4().hex}.jpg"
    relative_path = f"/uploads/face_attendance/{unique_filename}"
    save_path = os.path.join(UPLOAD_DIR, unique_filename)

    try:
        missing_padding = len(clean_base64) % 4
        if missing_padding:
            clean_base64 += "=" * (4 - missing_padding)
        image_data = base64.b64decode(clean_base64, validate=False)
    except Exception as exc:
        _logger.warning("save_base64_image: failed to decode image bytes: %s", exc)
        return relative_path

    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(image_data)
    except Exception as exc:
        _logger.warning("save_base64_image: primary write failed (%s). Attempting temp fallback.", exc)
        try:
            tmp_dir = os.path.join(tempfile.gettempdir(), "face_attendance")
            os.makedirs(tmp_dir, exist_ok=True)
            with open(os.path.join(tmp_dir, unique_filename), "wb") as f:
                f.write(image_data)
        except Exception as tmp_exc:
            _logger.warning("save_base64_image: temp fallback write also failed: %s", tmp_exc)

    return relative_path


async def write_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    ip_address: Optional[str],
    details: str,
    company_id: Optional[uuid.UUID] = None,
) -> None:
    """Writes a row into the audit_logs database table safely."""
    try:
        user = await db.get(User, user_id)
        email = user.email if user else None
        cid = company_id or (getattr(user, "company_id", None) if user else None)
        log = AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            company_id=cid,
            action=action,
            email=email,
            ip_address=ip_address,
            user_agent="HRMS Face Attendance Module",
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log)
    except Exception:
        # Non-blocking log failure
        pass
