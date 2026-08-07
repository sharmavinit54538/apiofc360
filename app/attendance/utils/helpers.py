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


async def write_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    ip_address: Optional[str],
    details: str,
) -> None:
    """Writes a row into the audit_logs database table."""
    try:
        user = await db.get(User, user_id)
        email = user.email if user else None
        log = AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
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
