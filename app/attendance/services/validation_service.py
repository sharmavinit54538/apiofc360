"""Validation service for Face Attendance business rules, biometric matching, and file uploads."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional, Union

from fastapi import HTTPException, UploadFile, status
from zoneinfo import ZoneInfo

from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.utils.biometric_crypto import decrypt_face_embedding
from app.models.employee import Employee
from app.attendance.utils.timezone import now_utc

# Validation Constants
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit
MAX_SHIFT_HOURS = 16  # Maximum shift duration before considering session stale


class ActiveSessionInfo:
    """Info about an active session for frontend sync."""
    def __init__(self, session_id: str, check_in_time: str, status: str, date: str, shift_name: str | None = None, is_late: bool = False):
        self.session_id = session_id
        self.check_in_time = check_in_time
        self.status = status
        self.date = date
        self.shift_name = shift_name
        self.is_late = is_late

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "check_in_time": self.check_in_time,
            "status": self.status,
            "date": self.date,
            "shift_name": self.shift_name,
            "is_late": self.is_late,
        }


class AttendanceValidationService:
    """Validates daily Face Attendance business rules, biometrics, and uploads."""

    def __init__(self, repo: AttendanceRepository) -> None:
        self.repo = repo

    def validate_image(self, file: UploadFile) -> None:
        """Validates file suffix and file size <= 10MB."""
        filename = file.filename or ""
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": f"Invalid file format '.{ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
                },
            )

        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": f"File is too large ({size / (1024*1024):.2f}MB). Maximum allowed is 10MB.",
                },
            )

    def validate_employee(self, employee: Employee | None, company_id: uuid.UUID) -> Employee:
        """Asserts employee profile exists, is active, and matches authenticated company scope."""
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "EMPLOYEE_NOT_FOUND", "message": "Employee record not found for this user account."},
            )
        if employee.company_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "TENANT_MISMATCH", "message": "Employee company context mismatch."},
            )
        if not getattr(employee, "is_active", True) or getattr(employee, "is_deleted", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "EMPLOYEE_INACTIVE", "message": "Employee account is inactive or deactivated."},
            )
        return employee

    async def assert_no_active_session_or_auto_close(
        self, 
        employee_id: uuid.UUID, 
        company_tz: ZoneInfo,
        max_shift_hours: int = MAX_SHIFT_HOURS
    ) -> Optional[ActiveSessionInfo]:
        """
        Check for active session. If stale (previous day or expired shift), auto-close it.
        If same-day active session, return ActiveSessionInfo for frontend sync.
        
        Returns:
            - None: No active session or stale session was auto-closed
            - ActiveSessionInfo: Same-day active session exists (frontend should sync to checked-in state)
        """
        # First check for active session with details
        active_details = await self.repo.get_active_session_with_details(employee_id)
        
        if not active_details:
            return None  # No active session

        # Check if the active session is stale (previous day or expired shift)
        check_in_time_str = active_details["check_in_time"]
        if not check_in_time_str:
            # No check-in time, treat as stale
            await self.repo.auto_close_stale_session(employee_id, company_tz, max_shift_hours)
            return None

        # Parse check-in time and compare with today in company timezone
        check_in_dt = datetime.fromisoformat(check_in_time_str.replace('Z', '+00:00'))
        check_in_local = check_in_dt.astimezone(company_tz)
        today_local = now_utc().astimezone(company_tz).date()
        session_date = check_in_local.date()

        # Check if session is from previous day
        is_previous_day = session_date < today_local
        
        # Check if session has exceeded max shift duration
        session_duration_hours = (now_utc() - check_in_dt).total_seconds() / 3600
        is_expired_shift = session_duration_hours > max_shift_hours

        if is_previous_day or is_expired_shift:
            # Stale session - auto-close it
            await self.repo.auto_close_stale_session(employee_id, company_tz, max_shift_hours)
            return None

        # Same-day active session - return details for frontend sync
        return ActiveSessionInfo(
            session_id=active_details["session_id"],
            check_in_time=active_details["check_in_time"],
            status=active_details["status"],
            date=active_details["date"],
            shift_name=active_details.get("shift_name"),
            is_late=active_details.get("is_late", False),
        )

    async def assert_no_duplicate_checkin(self, employee_id: uuid.UUID, dt: date) -> None:
        """Asserts no check-in record exists on date (One attendance per day rule)."""
        record = await self.repo.get_record_by_date(employee_id, dt)
        if record:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ALREADY_CHECKED_IN",
                    "message": f"Employee has already checked in on {dt.isoformat()}. Only one attendance per day is allowed.",
                },
            )

    def validate_face_enrolled(self, employee: Employee) -> List[float]:
        """Enforces mandatory face enrollment guard and returns decrypted enrolled embedding.
        
        Raises HTTPException 403 with FACE_NOT_ENROLLED if face is not enrolled.
        """
        raw_embedding = getattr(employee, "face_embedding", None)
        is_enrolled = getattr(employee, "is_face_enrolled", False)

        if not is_enrolled or not raw_embedding:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FACE_NOT_ENROLLED",
                    "message": "Face not enrolled. Please complete face registration first.",
                },
            )

        decrypted = decrypt_face_embedding(raw_embedding)
        if not decrypted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FACE_NOT_ENROLLED",
                    "message": "Enrolled biometric template could not be verified. Please re-enroll your face.",
                },
            )
        return decrypted

    def validate_face_match(
        self,
        employee: Employee,
        live_embedding: List[float],
        threshold: float = MATCH_DISTANCE_THRESHOLD,
    ) -> float:
        """Validates that live face embedding matches registered profile embedding.
        
        Raises HTTPException 400 with FACE_MISMATCH if distance > threshold.
        """
        saved_embedding = self.validate_face_enrolled(employee)

        is_match, distance = FaceRecognitionService.compare_embeddings(
            saved_embedding=saved_embedding,
            live_embedding=live_embedding,
            threshold=threshold,
        )

        if not is_match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_MISMATCH",
                    "message": f"Face verification failed (distance {distance:.3f} > threshold {threshold:.2f}). Face does not match registered profile.",
                },
            )

        return distance
