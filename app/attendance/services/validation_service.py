"""Validation service for Face Attendance business rules, biometric matching, and file uploads."""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import HTTPException, UploadFile, status

from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.utils.biometric_crypto import decrypt_face_embedding
from app.models.employee import Employee

# Validation Constants
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit


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

    async def assert_no_active_session(self, employee_id: uuid.UUID) -> None:
        """Asserts no active check-in session already exists."""
        active = await self.repo.get_active_session(employee_id)
        if active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ALREADY_CHECKED_IN",
                    "message": "Active check-in session already exists. Please check out of your previous session first.",
                },
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
