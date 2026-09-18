"""Authenticated Face Attendance photo streaming router."""

from __future__ import annotations

import logging
import mimetypes
import os
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.attendance.models.attendance import Attendance
from app.models.employee import Employee

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/face/image/{attendance_id}",
    summary="Stream authenticated face attendance photograph proof",
    response_class=FileResponse,
)
async def get_attendance_image(
    attendance_id: uuid.UUID,
    image_type: str = Query("checkin", alias="type", description="Image type: 'checkin' or 'checkout'"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> FileResponse:
    """Securely stream check-in or check-out photo proof with RBAC authorization."""
    # 1. Fetch attendance record
    attendance = await db.get(Attendance, attendance_id)
    if not attendance:
        raise AppException(
            message="Attendance record not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Extract requester identity
    user_id_str = claims.get("sub") if isinstance(claims, dict) else None
    user_role = (claims.get("role") or "").upper() if isinstance(claims, dict) else ""
    user_company_id_str = claims.get("company_id") if isinstance(claims, dict) else None

    if not user_id_str:
        raise AppException(
            message="Authentication context missing.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user_id = uuid.UUID(str(user_id_str))
    user_company_id = uuid.UUID(str(user_company_id_str)) if user_company_id_str else None

    # 3. RBAC authorization check
    authorized = False

    # Super Admin can view all
    if user_role in ("SUPER_ADMIN", "SUPERADMIN"):
        authorized = True

    # Company Admin / HR Admin can view within same tenant
    elif user_role in ("ADMIN", "HR_ADMIN", "IT_ADMIN") and user_company_id and attendance.company_id == user_company_id:
        authorized = True

    else:
        # Check if caller is the owning employee or their manager
        emp_res = await db.execute(select(Employee).where(Employee.user_id == user_id))
        current_emp = emp_res.scalars().first()

        if current_emp:
            # Own photo
            if current_emp.id == attendance.employee_id:
                authorized = True
            # Manager of the employee
            elif user_role in ("MANAGER", "TEAM_LEAD"):
                target_emp = await db.get(Employee, attendance.employee_id)
                if target_emp and target_emp.reporting_manager_id == current_emp.id:
                    authorized = True

    if not authorized:
        logger.warning(
            "Unauthorized access attempt to attendance photo | attendance_id=%s, user_id=%s, role=%s",
            attendance_id,
            user_id,
            user_role,
        )
        raise AppException(
            message="You are not authorized to view this attendance photograph.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 4. Resolve local file path
    target_type = (image_type or "checkin").strip().lower()
    if target_type == "checkout":
        relative_path = attendance.checkout_image_url
    else:
        relative_path = attendance.face_image_url

    if not relative_path:
        raise AppException(
            message=f"No {target_type} photograph recorded for this attendance record.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Normalize file path and guard against traversal
    normalized_path = os.path.normpath(relative_path)
    if os.path.isabs(normalized_path):
        file_path = normalized_path
    else:
        file_path = os.path.abspath(os.path.join(os.getcwd(), normalized_path))

    if not os.path.isfile(file_path):
        logger.error("Attendance image file missing on disk | path=%s", file_path)
        raise AppException(
            message="Image file not found on disk.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    media_type, _ = mimetypes.guess_type(file_path)
    return FileResponse(
        path=file_path,
        media_type=media_type or "image/jpeg",
        filename=os.path.basename(file_path),
    )
