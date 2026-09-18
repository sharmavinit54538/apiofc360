"""Daily Face Attendance check-in service with AI biometric verification."""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_base64_image, save_face_image, write_audit_log


class AttendanceCheckInService:
    """Handles logic for AI Face Recognition check-in and validation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)

    async def check_in_with_face_base64(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        image_base64: str,
        location: Optional[dict[str, Any]] = None,
        notes: Optional[str] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Attendance:
        """Execute AI face verification check-in with mandatory enrollment guard.
        
        Steps:
        1. Resolve and validate employee profile for authenticated user.
        2. Guard: Assert employee has enrolled their face (403 FACE_NOT_ENROLLED if False).
        3. Assert no active session and no duplicate check-in today.
        4. Decode base64 image and extract 128-d face embedding (400 if 0 or >1 faces).
        5. Verify match against registered baseline embedding (400 FACE_MISMATCH if distance > 0.50).
        6. Persist Attendance record: status='Present', punch_type='IN', verified=True.
        """
        # 1. Resolve employee
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Mandatory enrollment check
        self.validator.validate_face_enrolled(employee)

        # 3. Session constraints
        await self.validator.assert_no_active_session(employee.id)
        today = date.today()
        await self.validator.assert_no_duplicate_checkin(employee.id, today)

        # 4. Extract live face embedding
        rgb_array = FaceRecognitionService.decode_base64_image(image_base64)
        live_embedding = FaceRecognitionService.extract_face_embedding(rgb_array)

        # 5. Biometric comparison against stored baseline
        distance = self.validator.validate_face_match(
            employee=employee,
            live_embedding=live_embedding,
            threshold=MATCH_DISTANCE_THRESHOLD,
        )

        # 6. Save image locally
        image_url = await save_base64_image(image_base64, prefix="checkin")

        # Parse optional coordinates
        latitude = None
        longitude = None
        if location and isinstance(location, dict):
            try:
                lat_val = location.get("latitude") or location.get("lat")
                lng_val = location.get("longitude") or location.get("lng") or location.get("long")
                if lat_val is not None:
                    latitude = float(lat_val)
                if lng_val is not None:
                    longitude = float(lng_val)
            except (ValueError, TypeError):
                pass

        # Create Attendance record
        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee.id,
            company_id=company_id,
            date=today,
            check_in_time=datetime.now(timezone.utc),
            check_out_time=None,
            face_image_url=image_url,
            captured_face_url=image_url,
            status="Present",
            punch_type="IN",
            verified=True,
            punch_verified_by="FACE",
            notes=notes,
            latitude=latitude,
            longitude=longitude,
            device_info=device_info,
            ip_address=ip_address,
        )
        self.db.add(record)

        # Write audit log
        details = (
            f"AI Face Check-In: Date={today} | Distance={distance:.4f} (<= {MATCH_DISTANCE_THRESHOLD}) "
            f"| GPS={latitude},{longitude} | Image={image_url}"
        )
        await write_audit_log(self.db, user_id, "AI_FACE_CHECK_IN", ip_address, details)

        await self.db.commit()
        await self.db.refresh(record)

        record.employee_name = f"{employee.first_name} {employee.last_name}"
        return record

    async def check_in(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        file: UploadFile,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Attendance:
        """Backwards-compatible multipart check-in route."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # If employee has enrolled face, enforce biometric verification
        if getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None):
            self.validator.validate_image(file)
            file_bytes = await file.read()
            image_b64 = base64.b64encode(file_bytes).decode("utf-8")
            loc_dict = {"latitude": latitude, "longitude": longitude} if latitude is not None and longitude is not None else None
            return await self.check_in_with_face_base64(
                user_id=user_id,
                company_id=company_id,
                image_base64=image_b64,
                location=loc_dict,
                device_info=device_info,
                ip_address=ip_address,
            )

        # If employee has not enrolled face, fail with mandatory enrollment guard
        self.validator.validate_face_enrolled(employee)
