"""Authenticated file download endpoints for private uploads.

These endpoints replace public StaticFiles mounts for sensitive directories
(onboarding, connect, qrcodes, face_attendance) with authenticated,
tenant-scoped downloads that validate path traversal and record ownership.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.connect import ConnectSharedFile

router = APIRouter(prefix="/api/v1/files", tags=["Authenticated File Downloads"])


def _safe_join(base_dir: str, requested_path: str) -> Path | None:
    """Safely resolve a requested path within a base directory, preventing path traversal.

    Returns resolved Path if safe, None if path traversal detected.
    """
    try:
        base = Path(base_dir).resolve()
        requested = (base / requested_path).resolve()
        # Ensure requested path is within base directory
        if not requested.is_relative_to(base):
            return None
        return requested
    except Exception:
        return None


def _get_company_id_from_claims(claims: dict) -> uuid.UUID | None:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        return None
    try:
        return uuid.UUID(str(co_id_str))
    except ValueError:
        return None


# ── Connect Shared Files ─────────────────────────────────────────────


@router.get(
    "/connect/{file_id}",
    summary="Download connect shared file (authenticated, tenant-scoped)",
)
async def download_connect_file(
    file_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Download a connect shared file after validating tenant scope."""
    company_id = _get_company_id_from_claims(claims)
    if not company_id:
        raise HTTPException(status_code=403, detail="No company association found.")

    stmt = select(ConnectSharedFile).where(
        ConnectSharedFile.id == file_id,
        ConnectSharedFile.company_id == company_id,
    )
    res = await session.execute(stmt)
    file_record = res.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="File not found or access denied.")

    # Resolve file path safely
    if file_record.file_path:
        file_path = Path(file_record.file_path)
    elif file_record.file_url:
        relative = file_record.file_url.lstrip("/")
        file_path = _safe_join(settings.UPLOAD_DIR, relative)
    else:
        raise HTTPException(status_code=404, detail="File not found on disk.")

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk.")

    return FileResponse(
        path=str(file_path),
        filename=file_record.file_name,
        media_type=file_record.file_type or "application/octet-stream",
    )


# ── QR Codes (Job Application) ──────────────────────────────────────
# Note: QR codes for job applications are intentionally public for candidate scanning.
# They are generated on-demand and don't require authentication to download.
# If QR code privacy is needed in future, add a similar authenticated endpoint here.


# ── Face Attendance Images ──────────────────────────────────────────
# Note: Face attendance images are stored in S3/GCS object storage (biometric_storage.py)
# and accessed via presigned URLs. They are NOT served via local StaticFiles.
# No local download endpoint needed.