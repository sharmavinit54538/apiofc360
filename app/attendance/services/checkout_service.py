"""Daily Face Attendance check-out service with AI biometric verification and working hours calculation."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.break_service import BreakService
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.services.geofence_service import GeofenceService
from app.attendance.services.shift_service import ShiftService
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_base64_image, save_face_image, write_audit_log

logger = logging.getLogger(__name__)


class AttendanceCheckOutService:
    """Handles logic for checking out an employee with real face verification."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)
        self.break_service = BreakService(db)
        self.shift_service = ShiftService(db)
        self.geofence_service = GeofenceService(db)

    async def check_out_with_face_base64(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        image_base64: str,
        location: Optional[dict[str, Any]] = None,
        notes: Optional[str] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Attendance:
        """Execute AI face verification check-out.
        
        Steps:
        1. Resolve employee and validate company/active status.
        2. Verify employee has an active check-in session today without a check-out.
        3. Decode image, run quality checks & passive anti-spoofing liveness verification.
        4. Extract 128-d face embedding (ensuring exactly 1 face).
        5. Biometric comparison against enrolled baseline embedding (must match threshold <= 0.50).
        6. Geofence verification against database-configured office location if coordinates provided.
        7. Auto-complete open break session if employee forgot to end break before checkout.
        8. Calculate net working hours = (check_out_time - check_in_time) - break_duration.
        9. Evaluate shift overtime or early departure.
        10. Update Attendance record and write audit log.
        """
        # 1. Resolve employee
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Check for active session
        record = await self.repo.get_active_session(employee.id)
        if not record:
            # Check if already checked out today
            today_record = await self.repo.get_record_by_date(employee.id, date.today())
            if today_record and today_record.check_out_time is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "ALREADY_CHECKED_OUT",
                        "message": "You have already checked out for today.",
                    },
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "NO_ACTIVE_CHECKIN",
                    "message": "No active check-in session found. Please check in first.",
                },
            )

        # 3 & 4. Decode image, quality checks, anti-spoofing liveness, and embedding extraction
        rgb_array = FaceRecognitionService.decode_base64_image(image_base64)
        live_embedding, liveness_score = FaceRecognitionService.extract_face_embedding(
            rgb_array, enforce_liveness=True
        )

        # 5. Biometric comparison against stored baseline
        distance = self.validator.validate_face_match(
            employee=employee,
            live_embedding=live_embedding,
            threshold=MATCH_DISTANCE_THRESHOLD,
        )

        # 6. Geofence verification if location is provided
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

        if lat_val is not None and lng_val is not None:
            geofence_res = await self.geofence_service.verify_geofence(
                employee=employee,
                company_id=company_id,
                latitude=lat_val,
                longitude=lng_val,
                accuracy=accuracy_val,
            )
            # Log geofence result for audit
            logger.info("Checkout Geofence: %s", geofence_res)

        # 7. Auto-complete open break session if active
        now_dt = datetime.now(timezone.utc)
        active_break = await self.break_service.get_active_break_for_attendance(record.id)
        if active_break:
            delta_break = now_dt - active_break.break_start
            active_break.break_end = now_dt
            active_break.duration_minutes = round(max(0.0, delta_break.total_seconds() / 60.0), 2)
            active_break.status = "COMPLETED"

            all_breaks = await self.break_service.get_all_breaks_for_attendance(record.id)
            total_break_mins = sum(b.duration_minutes or 0.0 for b in all_breaks if b.id != active_break.id) + active_break.duration_minutes
            record.break_duration = round(total_break_mins / 60.0, 2)

        # 8. Calculate final working duration on backend
        gross_delta = now_dt - record.check_in_time
        gross_hours = max(0.0, gross_delta.total_seconds() / 3600.0)
        break_hours = record.break_duration or 0.0
        net_working_hours = round(max(0.0, gross_hours - break_hours), 2)

        # 9. Save image proof locally
        checkout_image_url = await save_base64_image(image_base64, prefix="checkout")

        # 10. Update record columns
        record.check_out_time = now_dt
        record.checkout_image_url = checkout_image_url
        record.working_hours = net_working_hours
        if lat_val is not None:
            record.latitude = lat_val
        if lng_val is not None:
            record.longitude = lng_val
        if accuracy_val is not None:
            record.location_accuracy = accuracy_val
        if notes:
            record.notes = f"{record.notes} | Checkout: {notes}" if record.notes else notes

        # 11. Evaluate shift engine checkout metrics
        shift_info = await self.shift_service.resolve_employee_shift(employee, record.date)
        eval_result = self.shift_service.evaluate_checkout(
            shift_info, now_dt, record.date, net_working_hours
        )

        # 12. Security Audit Log
        details = (
            f"Face Check-Out Verified: Date={record.date} | Dist={distance:.3f} | "
            f"Liveness={liveness_score:.2f} | NetHours={net_working_hours} (Gross={gross_hours:.2f}h, Break={break_hours:.2f}h) | "
            f"Overtime={eval_result.get('overtime_hours')}h | GPS={lat_val},{lng_val}"
        )
        await write_audit_log(self.db, user_id, "FACE_CHECK_OUT", ip_address, details, company_id=company_id)

        await self.db.commit()
        await self.db.refresh(record)

        record.employee_name = f"{employee.first_name} {employee.last_name}"
        return record

    async def check_out(
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
        """Multipart checkout route with full face biometric verification."""
        self.validator.validate_image(file)
        file_bytes = await file.read()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        loc_dict = {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy,
        }
        return await self.check_out_with_face_base64(
            user_id=user_id,
            company_id=company_id,
            image_base64=image_b64,
            location=loc_dict,
            device_info=device_info,
            ip_address=ip_address,
        )
