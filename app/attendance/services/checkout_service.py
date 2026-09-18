"""Daily Face Attendance check-out service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_face_image, write_audit_log
from app.core.exceptions import BadRequestException


class AttendanceCheckOutService:
    """Handles logic for checking out an employee."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)

    async def check_out(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        file: UploadFile,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Attendance:
        """Verify conditions, compute working hours, and record checkout."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        self.validator.validate_image(file)

        record = await self.repo.get_active_session(employee.id)
        if not record:
            raise BadRequestException("No active check-in session found. Please check in first.")

        # Save proof photo
        checkout_url = await save_face_image(file)

        checkout_time = datetime.now(timezone.utc)
        delta = checkout_time - record.check_in_time
        working_hours = round(delta.total_seconds() / 3600.0, 2)

        # Update columns
        record.check_out_time = checkout_time
        record.checkout_image_url = checkout_url
        record.working_hours = working_hours
        if latitude is not None:
            record.latitude = latitude
        if longitude is not None:
            record.longitude = longitude

        # Log to audit trail
        details = f"Face Check-Out: Date={record.date} | GPS={latitude},{longitude} | Image={checkout_url} | Hours={working_hours}"
        await write_audit_log(self.db, user_id, "FACE_CHECK_OUT", ip_address, details)

        await self.db.commit()
        await self.db.refresh(record)

        # Populate name attribute for response serialization
        record.employee_name = f"{employee.first_name} {employee.last_name}"
        return record
