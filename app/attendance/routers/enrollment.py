"""Face Attendance enrollment and status controller routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.user import User
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.schemas.face import FaceEnrollRequest, FaceStatusResponse
from app.attendance.services.face_service import FaceRecognitionService
from app.attendance.utils.helpers import save_base64_image, write_audit_log

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    return uuid.UUID(cid) if cid else None


@router.get(
    "/face-status",
    status_code=status.HTTP_200_OK,
    response_model=FaceStatusResponse,
    summary="Check if current employee face is enrolled",
)
@router.get(
    "/face/status",
    status_code=status.HTTP_200_OK,
    response_model=FaceStatusResponse,
    include_in_schema=False,
)
async def get_face_status(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FaceStatusResponse:
    """Check whether the authenticated employee has enrolled their face embedding."""
    user_id = _get_user_id(claims)
    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)

    if not employee:
        # Check user record directly if employee profile is not yet mapped
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User account not found.",
            )
        is_enrolled = getattr(user, "is_face_enrolled", False)
        enrolled_at = getattr(user, "face_enrolled_at", None)
        return FaceStatusResponse(
            is_enrolled=bool(is_enrolled),
            enrolled_at=enrolled_at.isoformat() if enrolled_at else None,
        )

    is_enrolled = bool(getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None))
    enrolled_at = getattr(employee, "face_enrolled_at", None)

    return FaceStatusResponse(
        is_enrolled=is_enrolled,
        enrolled_at=enrolled_at.isoformat() if enrolled_at else None,
    )


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
    
    1. Decode base64 image and detect face count.
    2. Enforce 1 face rule (0 => 400, >1 => 400).
    3. Extract 128-dimensional embedding.
    4. Save embedding to database and set is_face_enrolled=True, face_enrolled_at=now.
    5. Return 200 Face enrolled successfully.
    """
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found for this user account.",
        )

    # 1. Decode base64 image into RGB numpy array
    rgb_array = FaceRecognitionService.decode_base64_image(payload.image_base64)

    # 2 & 3. Detect and encode face
    embedding = FaceRecognitionService.extract_face_embedding(rgb_array)

    # 4. Save face photo to disk
    image_url = await save_base64_image(payload.image_base64, prefix="enroll")

    # 5. Persist to employee record
    now = datetime.now(timezone.utc)
    was_already_enrolled = bool(getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None))
    
    employee.face_embedding = embedding
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

    # 6. Audit log
    action = "FACE_RE_ENROLLED" if was_already_enrolled else "FACE_ENROLLED"
    details = f"Face {'Re-enrolled' if was_already_enrolled else 'Enrolled'}: Date={now.date()} | Image={image_url} | EmbeddingDim={len(embedding)}"
    await write_audit_log(db, user_id, action, None, details, company_id=company_id)

    await db.commit()
    await db.refresh(employee)

    msg = "Face re-enrolled successfully" if was_already_enrolled else "Face enrolled successfully"
    return {
        "success": True,
        "message": msg,
        "data": {
            "is_enrolled": True,
            "enrolled_at": now.isoformat(),
            "action": "re-enrolled" if was_already_enrolled else "enrolled",
        },
    }
