"""Daily Face Attendance check-in service with AI biometric verification, anti-spoofing, and shift engine."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.services.geofence_service import GeofenceService
from app.attendance.services.shift_service import ShiftService
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_base64_image, save_face_image, write_audit_log

logger = logging.getLogger(__name__)


class AttendanceCheckInService:
    """Handles logic for AI Face Recognition check-in, liveness, geofencing, and shift rules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)
        self.shift_service = ShiftService(db)
        self.geofence_service = GeofenceService(db)

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
        """Execute AI face verification check-in.
        
        Steps:
        1. Resolve employee and validate company/active status.
        2. Validate face is enrolled.
        3. Enforce 1 attendance per day rule (assert no active session & no duplicate today).
        4. Decode image, run quality checks & passive anti-spoofing liveness verification.
        5. Extract 128-d face embedding (exactly 1 face).
        6. Biometric comparison against enrolled baseline embedding.
        7. Geofence verification against database-configured office location.
        8. Shift engine evaluation (shift timing, grace period, late arrival calculation).
        9. Transactionally persist Attendance record (handles race conditions with DB constraints).
        10. Write security audit log.
        """
        # 1. Resolve employee
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Mandatory enrollment check
        self.validator.validate_face_enrolled(employee)

        # 3. Session constraints (1 attendance per day rule)
        today = date.today()
        await self.validator.assert_no_active_session(employee.id)
        await self.validator.assert_no_duplicate_checkin(employee.id, today)

        # 4 & 5. Decode image, quality checks, anti-spoofing liveness, and embedding extraction
        rgb_array = FaceRecognitionService.decode_base64_image(image_base64)
        live_embedding, liveness_score = FaceRecognitionService.extract_face_embedding(
            rgb_array, enforce_liveness=True
        )

        # 6. Biometric comparison against stored baseline
        distance = self.validator.validate_face_match(
            employee=employee,
            live_embedding=live_embedding,
            threshold=MATCH_DISTANCE_THRESHOLD,
        )

        # 7. Geofence verification
        lat_val: Optional[float] = None
        lng_val: Optional[float] = None
        accuracy_val: Optional[float] = None
        if location and isinstance(location, dict):
            try:
                lat_raw = location.get("latitude") or location.get("lat")
                lng_raw = location.get("longitude") or location.get("lng") or location.get("long")
                acc_raw = location.get("accuracy")
                if lat_raw is not None:
                    lat_val = float(lat_raw)
                if lng_raw is not None:
                    lng_val = float(lng_raw)
                if acc_raw is not None:
                    accuracy_val = float(acc_raw)
            except (ValueError, TypeError):
                pass

        geofence_res = await self.geofence_service.verify_geofence(
            employee=employee,
            company_id=company_id,
            latitude=lat_val,
            longitude=lng_val,
            accuracy=accuracy_val,
        )

        if not geofence_res["inside_geofence"] and geofence_res["status"] == "OUTSIDE_GEOFENCE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "OUTSIDE_GEOFENCE",
                    "message": geofence_res["message"],
                    "data": geofence_res,
                },
            )
        if geofence_res["status"] == "ACCURACY_LOW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "SUSPICIOUS_LOCATION",
                    "message": geofence_res["message"],
                    "data": geofence_res,
                },
            )

        # 8. Shift engine evaluation
        shift_info = await self.shift_service.resolve_employee_shift(employee, today)
        now_dt = datetime.now(timezone.utc)
        is_late, late_mins = self.shift_service.evaluate_checkin(shift_info, now_dt, today)

        # 9. Save image proof locally
        image_url = await save_base64_image(image_base64, prefix="checkin")

        # 10. Persist Attendance record with race-condition guard
        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee.id,
            company_id=company_id,
            date=today,
            check_in_time=now_dt,
            check_out_time=None,
            face_image_url=image_url,
            captured_face_url=image_url,
            status="Present",
            punch_type="IN",
            verified=True,
            punch_verified_by="FACE",
            notes=notes,
            latitude=lat_val,
            longitude=lng_val,
            location_accuracy=accuracy_val,
            liveness_score=liveness_score,
            face_distance=distance,
            is_late=is_late,
            late_minutes=late_mins,
            shift_id=shift_info.get("shift_id"),
            shift_name=shift_info.get("shift_name"),
            break_duration=0.0,
            device_info=device_info,
            ip_address=ip_address,
        )
        self.db.add(record)

        try:
            await self.db.commit()
            await self.db.refresh(record)
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ALREADY_CHECKED_IN",
                    "message": f"Attendance already recorded for {today.isoformat()}.",
                },
            )

        # 11. Write security audit log
        details = (
            f"Face Check-In Verified: Date={today} | Dist={distance:.3f} | "
            f"Liveness={liveness_score:.2f} | Late={is_late} ({late_mins}m) | "
            f"GPS={lat_val},{lng_val} ({geofence_res.get('status')})"
        )
        await write_audit_log(self.db, user_id, "FACE_CHECK_IN", ip_address, details, company_id=company_id)

        record.employee_name = f"{employee.first_name} {employee.last_name}"
        return record

    async def check_in(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        file: UploadFile,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        accuracy: Optional[float] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Attendance:
        """Multipart check-in route with full face biometric verification."""
        self.validator.validate_image(file)
        file_bytes = await file.read()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        loc_dict = {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy,
        }
        return await self.check_in_with_face_base64(
            user_id=user_id,
            company_id=company_id,
            image_base64=image_b64,
            location=loc_dict,
            device_info=device_info,
            ip_address=ip_address,
        )
