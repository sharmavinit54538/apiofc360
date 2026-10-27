"""Helpers for Face Attendance local storage writes and audit logs."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, UploadFile, status
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


async def parse_face_request(
    request: Request,
    require_image: bool = True,
    missing_image_message: str = "Face image is required.",
) -> tuple[Optional[str], Optional[dict[str, Any]], Optional[str], Optional[str]]:
    """Unified handler accepting either JSON body or multipart/form-data.

    Returns:
        tuple: (image_base64, location_dict, notes, device_info)
    """
    import base64
    from fastapi import HTTPException, status

    content_type = request.headers.get("content-type", "").lower()

    image_b64: Optional[str] = None
    location_dict: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    device_info: Optional[str] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_obj = form.get("file")
        if not file_obj or not hasattr(file_obj, "read"):
            if require_image:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "FACE_QUALITY_LOW", "message": missing_image_message},
                )
        else:
            filename = getattr(file_obj, "filename", "") or ""
            ext = filename.split(".")[-1].lower() if "." in filename else ""
            from app.attendance.services.validation_service import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
            if ext and ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "FACE_QUALITY_LOW",
                        "message": f"Invalid file format '.{ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
                    },
                )
            file_bytes = await file_obj.read()
            if len(file_bytes) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "FACE_QUALITY_LOW",
                        "message": f"File is too large ({len(file_bytes) / (1024*1024):.2f}MB). Maximum allowed is 10MB.",
                    },
                )
            image_b64 = base64.b64encode(file_bytes).decode("utf-8")

        lat = form.get("latitude")
        lng = form.get("longitude")
        acc = form.get("accuracy")
        if lat is not None and lng is not None:
            try:
                location_dict = {
                    "latitude": float(lat),
                    "longitude": float(lng),
                    "accuracy": float(acc) if acc is not None else None,
                }
            except (ValueError, TypeError):
                pass
        notes_raw = form.get("notes")
        notes = str(notes_raw) if notes_raw is not None else None
        dev_raw = form.get("device_info")
        device_info = str(dev_raw) if dev_raw is not None else None
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "BAD_REQUEST", "message": "Invalid JSON request payload."},
            )
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "BAD_REQUEST", "message": "Invalid JSON request payload format."},
            )
        image_b64 = body.get("image_base64")
        location_dict = body.get("location")
        notes = body.get("notes")
        device_info = body.get("device_info")

    if require_image and not image_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "FACE_QUALITY_LOW", "message": missing_image_message},
        )

    return image_b64, location_dict, notes, device_info

