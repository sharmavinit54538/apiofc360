"""Daily Face Attendance check-in service."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.services.validation_service import AttendanceValidationService
from app.attendance.utils.helpers import save_face_image, write_audit_log


class AttendanceCheckInService:
    """Handles logic for checking in an employee."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.validator = AttendanceValidationService(self.repo)

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
        """Verify conditions, save photo, and mark employee checked-in."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        employee = self.validator.validate_employee(employee, company_id)

        self.validator.validate_image(file)
        await self.validator.assert_no_active_session(employee.id)
        
        today = date.today()
        await self.validator.assert_no_duplicate_checkin(employee.id, today)

        # Save proof photo
        image_url = await save_face_image(file)

        # Create record
        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee.id,
            company_id=company_id,
            date=today,
            check_in_time=datetime.now(timezone.utc),
            check_out_time=None,
            face_image_url=image_url,
            latitude=latitude,
            longitude=longitude,
            device_info=device_info,
            ip_address=ip_address,
        )
        self.db.add(record)

        # Log to audit trail
        details = f"Face Check-In: Date={today} | GPS={latitude},{longitude} | Image={image_url}"
        await write_audit_log(self.db, user_id, "FACE_CHECK_IN", ip_address, details)

        await self.db.commit()
        await self.db.refresh(record)

        # Populate name attribute for response serialization
        record.employee_name = f"{employee.first_name} {employee.last_name}"
        return record
