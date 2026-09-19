"""Face Attendance enrollment and status controller routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.user import User
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.schemas.face import FaceEnrollRequest, FaceStatusResponse
from app.attendance.services.face_service import FaceRecognitionService
from app.attendance.utils.biometric_crypto import encrypt_face_embedding
from app.attendance.utils.helpers import save_base64_image, write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    return uuid.UUID(str(cid)) if cid else None


@router.get(
    "/face-status",
    status_code=status.HTTP_200_OK,
    summary="Check if current employee face is enrolled",
)
@router.get(
    "/face/status",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_face_status(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Check whether the authenticated employee has enrolled their face embedding."""
    user_id = _get_user_id(claims)
    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)

    if not employee:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "USER_NOT_FOUND", "message": "User account not found."},
            )
        is_enrolled = bool(getattr(user, "is_face_enrolled", False))
        enrolled_at = getattr(user, "face_enrolled_at", None)
        return {
            "success": True,
            "message": "Face enrollment status retrieved.",
            "data": {
                "is_enrolled": is_enrolled,
                "enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
            },
            "error": None,
        }

    is_enrolled = bool(getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None))
    enrolled_at = getattr(employee, "face_enrolled_at", None)

    return {
        "success": True,
        "message": "Face enrollment status retrieved.",
        "data": {
            "is_enrolled": is_enrolled,
            "enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
        },
        "error": None,
    }


@router.post(
    "/face-enroll",
    status_code=status.HTTP_200_OK,
    summary="Register employee face embedding for attendance",
)
@router.post(
    "/face/enroll",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def face_enroll(
    payload: FaceEnrollRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Enroll employee face biometrics.
    
    1. Authenticates employee from session claims.
    2. Verifies image: decodes base64, checks image quality (blur, lighting, size).
    3. Detects exactly 1 face (rejects 0 with FACE_NOT_FOUND, rejects >1 with MULTIPLE_FACES).
    4. Anti-spoofing / liveness validation.
    5. Extracts 128-dimensional biometric embedding.
    6. Prevents accidental duplicate enrollment unless explicitly confirmed (allow_re_enroll=True).
    7. Encrypts embedding at rest with AES-256.
    8. Persists to employee record and logs security audit event.
    """
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "EMPLOYEE_NOT_FOUND", "message": "Employee profile not found for this user account."},
        )

    # Prevent accidental duplicate enrollment unless explicitly flagged
    was_already_enrolled = bool(getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None))
    if was_already_enrolled and not payload.allow_re_enroll:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALREADY_ENROLLED",
                "message": "Face biometric is already registered for this account. Set 'allow_re_enroll' to true to replace existing biometric.",
            },
        )

    # 1. Decode base64 image into RGB numpy array
    rgb_array = FaceRecognitionService.decode_base64_image(payload.image_base64)

    # 2, 3, 4, 5. Detect single face, validate quality & liveness, and extract embedding
    raw_embedding, liveness_score = FaceRecognitionService.extract_face_embedding(
        rgb_array, enforce_liveness=True
    )

    # 6. Encrypt biometric embedding at rest
    encrypted_payload = encrypt_face_embedding(raw_embedding)

    # 7. Save reference photo to disk
    image_url = await save_base64_image(payload.image_base64, prefix="enroll")

    # 8. Persist to employee record
    now = datetime.now(timezone.utc)
    employee.face_embedding = encrypted_payload
    employee.is_face_enrolled = True
    employee.face_enrolled_at = now
    if not employee.profile_photo_url:
        employee.profile_photo_url = image_url

    # Also update user record if available
    user = await db.get(User, user_id)
    if user:
        if hasattr(user, "is_face_enrolled"):
            user.is_face_enrolled = True
        if hasattr(user, "face_enrolled_at"):
            user.face_enrolled_at = now

    # 9. Audit log
    action = "FACE_RE_ENROLLED" if was_already_enrolled else "FACE_ENROLLED"
    details = f"Face {'Re-enrolled' if was_already_enrolled else 'Enrolled'}: Date={now.date()} | Image={image_url} | Liveness={liveness_score:.2f}"
    await write_audit_log(db, user_id, action, None, details, company_id=company_id)

    await db.commit()
    await db.refresh(employee)

    msg = "Face re-enrolled successfully." if was_already_enrolled else "Face enrolled successfully."
    return {
        "success": True,
        "message": msg,
        "data": {
            "is_enrolled": True,
            "enrolled_at": now.isoformat(),
            "action": "re-enrolled" if was_already_enrolled else "enrolled",
            "liveness_score": liveness_score,
        },
        "error": None,
    }
