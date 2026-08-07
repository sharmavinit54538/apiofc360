"""Daily Face Attendance services facade aggregator."""

from __future__ import annotations

import uuid
from typing import Optional, Any
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.services.checkin_service import AttendanceCheckInService
from app.attendance.services.checkout_service import AttendanceCheckOutService
from app.attendance.services.history_service import AttendanceHistoryService
from app.attendance.services.analytics_service import AttendanceAnalyticsService


class AttendanceService:
    """Facade wrapping all daily Face Attendance sub-services."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.checkin_service = AttendanceCheckInService(db)
        self.checkout_service = AttendanceCheckOutService(db)
        self.history_service = AttendanceHistoryService(db)
        self.analytics_service = AttendanceAnalyticsService(db)

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
        """Invokes check-in service."""
        return await self.checkin_service.check_in(
            user_id, company_id, file, latitude, longitude, device_info, ip_address
        )

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
        """Invokes check-out service."""
        return await self.checkout_service.check_out(
            user_id, company_id, file, latitude, longitude, device_info, ip_address
        )

    async def get_today_attendance(self, user_id: uuid.UUID) -> dict:
        """Invokes today status query."""
        return await self.history_service.get_today_attendance(user_id)

    async def get_own_history(self, user_id: uuid.UUID, page: int, limit: int) -> tuple[list[Attendance], int]:
        """Invokes personal history query."""
        return await self.history_service.get_own_history(user_id, page, limit)

    async def get_team_attendance(
        self, manager_user_id: uuid.UUID, company_id: uuid.UUID, page: int, limit: int
    ) -> tuple[list[Attendance], int]:
        """Invokes team history query."""
        return await self.history_service.get_team_attendance(manager_user_id, company_id, page, limit)

    async def get_company_attendance(
        self, company_id: uuid.UUID, branch: Optional[str] = None, dept: Optional[str] = None, page: int = 1, limit: int = 20
    ) -> tuple[list[Attendance], int]:
        """Invokes company history query."""
        return await self.history_service.get_company_attendance(company_id, branch, dept, page, limit)

    async def get_company_analytics(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Invokes company analytics query."""
        return await self.analytics_service.get_company_analytics(company_id)
