"""Daily Face Attendance check-in service with AI biometric verification, anti-spoofing, and shift engine."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.services.geofence_service import GeofenceService
from app.attendance.services.shift_service import CheckinEval, ShiftService
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_base64_image, write_audit_log
from app.attendance.utils.timezone import get_company_tz, now_utc

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
        idempotency_key: Optional[str] = None,
    ) -> Attendance:
        """Execute AI face verification check-in.

        Steps:
        1. Resolve employee and validate company/active status.
        2. Validate face is enrolled.
        3. Check for existing attendance today (one per day rule).
        4. Decode image, run quality checks & passive anti-spoofing liveness verification.
        5. Extract 128-d face embedding (exactly 1 face).
        6. Biometric comparison against enrolled baseline embedding.
        7. Geofence verification against database-configured office location.
        8. Shift engine evaluation (shift timing, grace period, late arrival calculation).
        9. Transactionally persist Attendance record (DB partial unique index prevents duplicate active sessions).
        10. Write security audit log.
        """
        # 1. Resolve employee
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Mandatory enrollment check
        self.validator.validate_face_enrolled(employee)

        # 3. One attendance per day rule (date-based unique constraint)
        tz = await get_company_tz(self.db, str(company_id))
        now_dt = now_utc()
        # Use company timezone to determine business date for the "one per day" check
        business_date = now_dt.astimezone(tz).date() if hasattr(tz, 'tzname') else now_dt.date()
        await self.validator.assert_no_duplicate_checkin(employee.id, business_date)

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

        # 8. Shift engine evaluation (timezone-aware)
        resolved, business_date = await self.shift_service.resolve_for_timestamp(employee, now_dt, tz)
        eval_result: CheckinEval = self.shift_service.evaluate_checkin(resolved, now_dt)

        # 9. Save image proof locally
        image_url = await save_base64_image(image_base64, prefix="checkin")

        # 10. Persist Attendance record with race-condition guard via DB partial unique index
        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee.id,
            company_id=company_id,
            date=business_date,
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
            is_late=eval_result.is_late,
            late_minutes=eval_result.late_minutes,
            shift_id=resolved.shift_id,
            shift_name=resolved.shift_name,
            shift_source=resolved.source,
            scheduled_start=resolved.start_dt,
            scheduled_end=resolved.end_dt,
            is_off_day_work=eval_result.is_off_day_work,
            is_holiday_work=eval_result.is_holiday_work,
            break_duration=0.0,
            device_info=device_info,
            ip_address=ip_address,
        )
        self.db.add(record)

        try:
            await self.db.commit()
            await self.db.refresh(record)
        except IntegrityError as exc:
            await self.db.rollback()
            # Distinguish between partial unique index (active session) and date unique constraint (already checked in today)
            error_msg = str(exc.orig) if hasattr(exc, 'orig') and exc.orig else str(exc)
            if "uq_attendance_open_session" in error_msg:
                # Active session exists - employee hasn't checked out
                active_session = await self.repo.get_active_session(employee.id)
                if active_session:
                    check_in_str = active_session.check_in_time.isoformat() if active_session.check_in_time else "unknown"
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "ALREADY_CHECKED_IN",
                            "message": f"Active check-in session already exists since {check_in_str}. Please check out of your previous session first.",
                        },
                    )
            # Fall back to date-based duplicate check
            if "uq_employee_date_attendance" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ALREADY_CHECKED_IN",
                        "message": f"Attendance already recorded for {business_date.isoformat()}. Only one attendance per day is allowed.",
                    },
                )
            # Re-raise unexpected integrity errors
            logger.exception("Unexpected integrity error during check-in: %s", error_msg)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "DATABASE_ERROR",
                    "message": "Failed to record attendance due to a database constraint violation.",
                },
            )

        # 11. Write security audit log
        details = (
            f"Face Check-In Verified: Date={business_date} | Dist={distance:.3f} | "
            f"Liveness={liveness_score:.2f} | Late={eval_result.is_late} ({eval_result.late_minutes}m) | "
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