"""Enterprise Break Tracking Service for Face Attendance.

Enforces business rules:
- Cannot start break without active check-in
- Cannot start two breaks simultaneously
- Cannot end a break that is not active
- Cannot start/end break after checking out
- Automatically calculates session duration and total aggregated break hours
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.models.attendance_break import AttendanceBreak
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.attendance.services.geofence_service import GeofenceService
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_base64_image, write_audit_log
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class BreakService:
    """Handles break session lifecycle (start, end, and duration tracking) with face biometrics."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)
        self.geofence_service = GeofenceService(db)

    async def start_break(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        image_base64: str,
        location: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AttendanceBreak:
        """Starts a new break session for the authenticated employee with face verification."""
        # 1. Resolve employee and validate company/active status
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Existing business-rule checks run BEFORE expensive face processing
        today = date.today()
        record = await self.repo.get_record_by_date(employee.id, today)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_CHECKIN", "message": "Cannot start break without checking in today first."},
            )

        if record.check_out_time is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "ALREADY_CHECKED_OUT", "message": "Cannot take a break after checking out for the day."},
            )

        active_break = await self.get_active_break_for_attendance(record.id)
        if active_break:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BREAK_ACTIVE",
                    "message": "A break session is already active. Please end your current break first.",
                },
            )

        # 3. Mandatory biometric face verification
        if not image_base64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Face image is required for break verification."},
            )

        self.validator.validate_face_enrolled(employee)
        rgb_array = FaceRecognitionService.decode_base64_image(image_base64)
        live_embedding, liveness_score = FaceRecognitionService.extract_face_embedding(
            rgb_array, enforce_liveness=True
        )
        distance = self.validator.validate_face_match(
            employee=employee,
            live_embedding=live_embedding,
            threshold=MATCH_DISTANCE_THRESHOLD,
        )

        # 4. Optional geofence evaluation (non-blocking, logged for audit)
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
            try:
                geofence_res = await self.geofence_service.verify_geofence(
                    employee=employee,
                    company_id=company_id,
                    latitude=lat_val,
                    longitude=lng_val,
                    accuracy=accuracy_val,
                )
                logger.info("Break Start Geofence: %s", geofence_res)
            except Exception as geo_exc:
                logger.warning("Break Start Geofence check warning: %s", geo_exc)

        # 5. Save proof image
        start_image_url = await save_base64_image(image_base64, prefix="break_start")

        # 6. Persist AttendanceBreak session
        now = datetime.now(timezone.utc)
        break_session = AttendanceBreak(
            id=uuid.uuid4(),
            attendance_id=record.id,
            employee_id=employee.id,
            company_id=company_id,
            break_start=now,
            break_end=None,
            duration_minutes=None,
            status="ACTIVE",
            notes=notes,
            start_image_url=start_image_url,
            end_image_url=None,
            start_face_distance=round(distance, 4) if distance is not None else None,
            end_face_distance=None,
            start_liveness_score=round(liveness_score, 4) if liveness_score is not None else None,
            end_liveness_score=None,
            start_latitude=lat_val,
            start_longitude=lng_val,
            end_latitude=None,
            end_longitude=None,
        )
        self.db.add(break_session)

        # 7. Audit log with biometrics & GPS
        gps_str = f"{lat_val},{lng_val}" if lat_val is not None and lng_val is not None else "None"
        dist_str = f"{distance:.3f}" if distance is not None else "N/A"
        live_str = f"{liveness_score:.2f}" if liveness_score is not None else "N/A"
        details = (
            f"Break Started: Time={now.isoformat()} | Dist={dist_str} | "
            f"Liveness={live_str} | GPS={gps_str} | Notes={notes or 'None'}"
        )
        await write_audit_log(self.db, user_id, "BREAK_START", ip_address, details, company_id=company_id)

        await self.db.commit()
        await self.db.refresh(break_session)
        return break_session

    async def end_break(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        image_base64: Optional[str] = None,
        location: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
        is_auto_ended: bool = False,
    ) -> AttendanceBreak:
        """Ends the currently active break session with face verification and updates total duration."""
        # 1. Resolve employee and validate company/active status
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        # 2. Existing business-rule checks run BEFORE expensive face processing
        today = date.today()
        record = await self.repo.get_record_by_date(employee.id, today)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_CHECKIN", "message": "No active attendance session found."},
            )

        if record.check_out_time is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "ALREADY_CHECKED_OUT", "message": "Cannot take or end a break after checking out for the day."},
            )

        active_break = await self.get_active_break_for_attendance(record.id)
        if not active_break:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_BREAK", "message": "No active break session found to end."},
            )

        # 3. Mandatory biometric face verification (unless auto-ended during checkout)
        distance: Optional[float] = None
        liveness_score: Optional[float] = None
        end_image_url: Optional[str] = None

        if not is_auto_ended:
            if not image_base64:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "FACE_QUALITY_LOW", "message": "Face image is required for break verification."},
                )

            self.validator.validate_face_enrolled(employee)
            rgb_array = FaceRecognitionService.decode_base64_image(image_base64)
            live_embedding, liveness_score = FaceRecognitionService.extract_face_embedding(
                rgb_array, enforce_liveness=True
            )
            distance = self.validator.validate_face_match(
                employee=employee,
                live_embedding=live_embedding,
                threshold=MATCH_DISTANCE_THRESHOLD,
            )
            end_image_url = await save_base64_image(image_base64, prefix="break_end")

        # 4. Optional geofence evaluation
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
            try:
                geofence_res = await self.geofence_service.verify_geofence(
                    employee=employee,
                    company_id=company_id,
                    latitude=lat_val,
                    longitude=lng_val,
                    accuracy=accuracy_val,
                )
                logger.info("Break End Geofence: %s", geofence_res)
            except Exception as geo_exc:
                logger.warning("Break End Geofence check warning: %s", geo_exc)

        # 5. Calculate break duration
        now = datetime.now(timezone.utc)
        delta = now - active_break.break_start
        duration_minutes = round(max(0.0, delta.total_seconds() / 60.0), 2)

        active_break.break_end = now
        active_break.duration_minutes = duration_minutes
        active_break.status = "COMPLETED"
        if end_image_url:
            active_break.end_image_url = end_image_url
        if distance is not None:
            active_break.end_face_distance = round(distance, 4)
        if liveness_score is not None:
            active_break.end_liveness_score = round(liveness_score, 4)
        if lat_val is not None:
            active_break.end_latitude = lat_val
        if lng_val is not None:
            active_break.end_longitude = lng_val
        if notes:
            active_break.notes = f"{active_break.notes} | End: {notes}" if active_break.notes else notes
        if is_auto_ended:
            active_break.notes = (
                f"{active_break.notes} | Auto-ended at checkout"
                if active_break.notes
                else "Auto-ended at checkout"
            )

        # 6. Recompute total aggregated break duration in hours for attendance record
        all_breaks = await self.get_all_breaks_for_attendance(record.id)
        total_mins = sum(b.duration_minutes or 0.0 for b in all_breaks if b.id != active_break.id) + duration_minutes
        record.break_duration = round(total_mins / 60.0, 2)

        # 7. Audit log
        gps_str = f"{lat_val},{lng_val}" if lat_val is not None and lng_val is not None else "None"
        dist_str = f"{distance:.3f}" if distance is not None else "N/A"
        live_str = f"{liveness_score:.2f}" if liveness_score is not None else "N/A"
        details = (
            f"Break Ended: Duration={duration_minutes} mins | TotalBreakHrs={record.break_duration} | "
            f"Dist={dist_str} | Liveness={live_str} | GPS={gps_str}"
        )
        if is_auto_ended:
            details += " | Trigger=AutoCheckout"
        await write_audit_log(self.db, user_id, "BREAK_END", ip_address, details, company_id=company_id)

        await self.db.commit()
        await self.db.refresh(active_break)
        return active_break

    async def get_active_break_for_attendance(self, attendance_id: uuid.UUID) -> Optional[AttendanceBreak]:
        """Finds any active break for the attendance record."""
        stmt = select(AttendanceBreak).where(
            and_(
                AttendanceBreak.attendance_id == attendance_id,
                AttendanceBreak.status == "ACTIVE",
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all_breaks_for_attendance(self, attendance_id: uuid.UUID) -> List[AttendanceBreak]:
        """Retrieves all break sessions for an attendance record."""
        stmt = (
            select(AttendanceBreak)
            .where(AttendanceBreak.attendance_id == attendance_id)
            .order_by(AttendanceBreak.break_start.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_break_summary(self, attendance_id: uuid.UUID) -> Dict[str, Any]:
        """Returns structured break status summary for an attendance record."""
        breaks = await self.get_all_breaks_for_attendance(attendance_id)
        active_break = next((b for b in breaks if b.status == "ACTIVE"), None)

        total_mins = sum(b.duration_minutes or 0.0 for b in breaks if b.duration_minutes is not None)
        if active_break:
            current_elapsed = (datetime.now(timezone.utc) - active_break.break_start).total_seconds() / 60.0
            total_mins += max(0.0, current_elapsed)

        return {
            "is_on_break": active_break is not None,
            "current_break": {
                "id": str(active_break.id),
                "break_start": active_break.break_start.isoformat(),
                "notes": active_break.notes,
                "start_image_url": active_break.start_image_url,
                "start_face_distance": active_break.start_face_distance,
                "start_liveness_score": active_break.start_liveness_score,
                "start_latitude": active_break.start_latitude,
                "start_longitude": active_break.start_longitude,
            } if active_break else None,
            "total_break_minutes": round(total_mins, 1),
            "total_break_hours": round(total_mins / 60.0, 2),
            "break_sessions_count": len(breaks),
            "breaks": [
                {
                    "id": str(b.id),
                    "break_start": b.break_start.isoformat(),
                    "break_end": b.break_end.isoformat() if b.break_end else None,
                    "duration_minutes": b.duration_minutes,
                    "status": b.status,
                    "notes": b.notes,
                    "start_image_url": b.start_image_url,
                    "end_image_url": b.end_image_url,
                    "start_face_distance": b.start_face_distance,
                    "end_face_distance": b.end_face_distance,
                    "start_liveness_score": b.start_liveness_score,
                    "end_liveness_score": b.end_liveness_score,
                    "start_latitude": b.start_latitude,
                    "start_longitude": b.start_longitude,
                    "end_latitude": b.end_latitude,
                    "end_longitude": b.end_longitude,
                }
                for b in breaks
            ],
        }

