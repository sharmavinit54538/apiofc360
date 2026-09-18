"""Daily Face Attendance request validation service."""

from __future__ import annotations

import math
import uuid
from datetime import date
from fastapi import UploadFile, status

from app.core.exceptions import AppException, ConflictException
from app.models.employee import Employee
from app.models.company import Company
from app.attendance.repositories.attendance_repository import AttendanceRepository

# Validation Constants
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit

# Magic byte signatures
FILE_SIGNATURES = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}


class AttendanceValidationService:
    """Validates daily Face Attendance business rules and uploads."""

    def __init__(self, repo: AttendanceRepository) -> None:
        self.repo = repo

    def validate_image(self, file: UploadFile) -> None:
        """Validates file suffix, emptiness, magic bytes, and file size <= 10MB."""
        filename = file.filename or ""
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message=f"Invalid file format '.{ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Check file size & emptiness
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size == 0:
            raise AppException(
                message="Uploaded file is empty.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if size > MAX_FILE_SIZE:
            raise AppException(
                message=f"File is too large ({size / (1024*1024):.2f}MB). Maximum allowed is 10MB.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Validate magic bytes content
        file_header = file.file.read(16)
        file.file.seek(0)
        self._validate_file_signature(file_header, ext)

    def _validate_file_signature(self, file_header: bytes, ext: str) -> None:
        """Validate file magic bytes match expected image extension signature."""
        if ext == "webp":
            if file_header.startswith(b"RIFF") and len(file_header) >= 12 and file_header[8:12] == b"WEBP":
                return
            raise AppException(
                message=f"File content does not match expected format for '{ext}'. File may be corrupted or mislabeled.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        expected = FILE_SIGNATURES.get(ext, [])
        for sig in expected:
            if file_header.startswith(sig):
                return

        raise AppException(
            message=f"File content does not match expected format for '{ext}'. File may be corrupted or mislabeled.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    def validate_location(
        self,
        company: Company | None,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        """Validates GPS coordinates against company geofence settings using Haversine formula."""
        if not company:
            return

        office_lat = getattr(company, "office_latitude", None)
        office_lon = getattr(company, "office_longitude", None)
        radius_meters = getattr(company, "geofence_radius_meters", None)

        if office_lat is None or office_lon is None or radius_meters is None:
            hr_settings = getattr(company, "hr_settings", None) or {}
            if isinstance(hr_settings, dict):
                office_lat = office_lat if office_lat is not None else hr_settings.get("office_latitude")
                office_lon = office_lon if office_lon is not None else hr_settings.get("office_longitude")
                radius_meters = radius_meters if radius_meters is not None else hr_settings.get("geofence_radius_meters")

        # Geofence validation is opt-in per company
        if office_lat is None or office_lon is None or radius_meters is None:
            return

        if latitude is None or longitude is None:
            raise AppException(
                message="Location coordinates (latitude and longitude) are required for attendance.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        earth_radius = 6371000.0  # meters
        phi1 = math.radians(float(office_lat))
        phi2 = math.radians(float(latitude))
        delta_phi = math.radians(float(latitude) - float(office_lat))
        delta_lambda = math.radians(float(longitude) - float(office_lon))

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        distance = earth_radius * c

        if distance > float(radius_meters):
            raise AppException(
                message=f"Location coordinates are outside the office geofence ({round(distance, 1)}m away, max allowed {radius_meters}m).",
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
