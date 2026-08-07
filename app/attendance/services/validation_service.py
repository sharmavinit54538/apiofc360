"""Daily Face Attendance request validation service."""

from __future__ import annotations

import uuid
from datetime import date
from fastapi import UploadFile, status

from app.core.exceptions import AppException, ConflictException
from app.models.employee import Employee
from app.attendance.repositories.attendance_repository import AttendanceRepository

# Validation Constants
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit


class AttendanceValidationService:
    """Validates daily Face Attendance business rules and uploads."""

    def __init__(self, repo: AttendanceRepository) -> None:
        self.repo = repo

    def validate_image(self, file: UploadFile) -> None:
        """Validates file suffix and file size <= 10MB."""
        filename = file.filename or ""
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message=f"Invalid file format '.{ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Check file size (approximate using file object seek if available)
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > MAX_FILE_SIZE:
            raise AppException(
                message=f"File is too large ({size / (1024*1024):.2f}MB). Maximum allowed is 10MB.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def validate_employee(self, employee: Employee | None, company_id: uuid.UUID) -> Employee:
        """Asserts employee profile exists and matches authenticated company scope."""
        if not employee:
            raise AppException(
                message="Employee record not found for this user account.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if employee.company_id != company_id:
            raise AppException(
                message="Employee company mismatch context.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return employee

    async def assert_no_active_session(self, employee_id: uuid.UUID) -> None:
        """Asserts no active check-in session already exists."""
        active = await self.repo.get_active_session(employee_id)
        if active:
            raise ConflictException(
                message="Active check-in session already exists. Please check out of your previous session first."
            )

    async def assert_no_duplicate_checkin(self, employee_id: uuid.UUID, dt: date) -> None:
        """Asserts no check-in record exists on date."""
        record = await self.repo.get_record_by_date(employee_id, dt)
        if record:
            raise ConflictException(
                message=f"Employee has already checked in on {dt.isoformat()}."
            )
