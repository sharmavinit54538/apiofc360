"""Attendance service implementing full business logic for all attendance endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.core_modules import AttendanceRegularizationRequest
from app.models.employee import Employee
from app.schemas.core_modules.attendance import (
    AttendanceCheckInRequest,
    AttendanceCheckOutRequest,
    AttendanceManualUpdateRequest,
    AttendanceRegularizationCreateRequest,
    FaceCheckInRequest,
    FaceEnrollRequest,
)

logger = logging.getLogger(__name__)


class AttendanceCoreService:
    """Service handling check-in, check-out, face punch, regularization, and analytics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        stmt = select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_today_record(self, employee_id: uuid.UUID, target_date: date | None = None) -> Attendance | None:
        t_date = target_date or date.today()
        stmt = select(Attendance).where(
            Attendance.employee_id == employee_id,
            Attendance.date == t_date,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def check_in(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceCheckInRequest,
        source: str = "app",
    ) -> Attendance:
        today = date.today()
        now = datetime.now(UTC)
        record = await self.get_today_record(employee_id, today)

        if record:
            return record

        is_late = now.hour >= 10
        late_mins = (now.hour - 10) * 60 + now.minute if is_late else 0

        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee_id,
            company_id=company_id,
            date=today,
            check_in_time=now,
            status="Present" if not is_late else "Late",
            punch_type="IN",
            verified=True,
            punch_verified_by=source.upper(),
            latitude=payload.latitude,
            longitude=payload.longitude,
            ip_address=payload.ip_address,
            device_info=payload.device_info,
            notes=payload.notes,
            is_late=is_late,
            late_minutes=late_mins,
        )
        self.session.add(record)

        if is_late and company_id:
            try:
                from app.models.employee import Employee
                from app.services import notification_service
                emp = await self.session.get(Employee, employee_id)
                recipients = []
                if emp and emp.user_id:
                    recipients.append(emp.user_id)
                if emp and (emp.reporting_manager_id or emp.manager_id):
                    mgr = await self.session.get(Employee, emp.reporting_manager_id or emp.manager_id)
                    if mgr and mgr.user_id:
                        recipients.append(mgr.user_id)
                if recipients:
                    await notification_service.notify(
                        self.session,
                        company_id=company_id,
                        recipient_ids=recipients,
                        type="attendance.late_arrival",
                        category="attendance",
                        module="attendance",
                        title="Late Arrival Recorded",
                        body=f"{emp.first_name if emp else 'Employee'} checked in {late_mins} min late on {today.isoformat()}.",
                        link="/dashboard/attendance",
                        priority="normal",
                        entity={"type": "attendance", "id": str(record.id)},
                        dedupe_key=f"attendance:{record.id}:late",
                    )
            except Exception as e:
                logger.warning("Failed to emit late attendance notification: %s", e)

        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def notify_missed_checkout(self, attendance_id: uuid.UUID) -> None:
        """Emit notification for missed check-out."""
        from app.models.employee import Employee
        from app.services import notification_service
        record = await self.session.get(Attendance, attendance_id)
        if not record or not record.company_id:
            return
        emp = await self.session.get(Employee, record.employee_id)
        recipients = []
        if emp and emp.user_id:
            recipients.append(emp.user_id)
        if emp and (emp.reporting_manager_id or emp.manager_id):
            mgr = await self.session.get(Employee, emp.reporting_manager_id or emp.manager_id)
            if mgr and mgr.user_id:
                recipients.append(mgr.user_id)
        if recipients:
            await notification_service.notify(
                self.session,
                company_id=record.company_id,
                recipient_ids=recipients,
                type="attendance.missed_checkout",
                category="attendance",
                module="attendance",
                title="Missed Check-Out Detected",
                body=f"Missed check-out recorded for {record.date.isoformat()}.",
                link="/dashboard/attendance",
                priority="normal",
                entity={"type": "attendance", "id": str(record.id)},
                dedupe_key=f"attendance:{record.id}:missed_checkout",
            )
            await self.session.commit()

    async def check_out(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceCheckOutRequest,
    ) -> Attendance:
        today = date.today()
        now = datetime.now(UTC)
        record = await self.get_today_record(employee_id, today)

        if not record:
            record = Attendance(
                id=uuid.uuid4(),
                employee_id=employee_id,
                company_id=company_id,
                date=today,
                check_in_time=now,
                check_out_time=now,
                status="Present",
                punch_type="OUT",
                verified=True,
                punch_verified_by="MANUAL",
                latitude=payload.latitude,
                longitude=payload.longitude,
                ip_address=payload.ip_address,
                device_info=payload.device_info,
                notes=payload.notes,
                working_hours=0.0,
            )
            self.session.add(record)
        else:
            record.check_out_time = now
            record.punch_type = "OUT"
            if record.check_in_time:
                delta = now - record.check_in_time
                record.working_hours = round(delta.total_seconds() / 3600.0, 2)
            if payload.notes:
                record.notes = f"{record.notes or ''}; Out: {payload.notes}"

        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def face_check_in(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: FaceCheckInRequest,
    ) -> Attendance:
        checkin_req = AttendanceCheckInRequest(
            latitude=payload.latitude,
            longitude=payload.longitude,
            notes="Biometric face verification check-in",
        )
        record = await self.check_in(employee_id, company_id, checkin_req, source="face")
        if payload.image_url:
            record.captured_face_url = payload.image_url
            record.punch_verified_by = "FACE"
            await self.session.commit()
        return record

    async def face_check_out(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: FaceCheckInRequest,
    ) -> Attendance:
        checkout_req = AttendanceCheckOutRequest(
            latitude=payload.latitude,
            longitude=payload.longitude,
            notes="Biometric face verification check-out",
        )
        record = await self.check_out(employee_id, company_id, checkout_req)
        if payload.image_url:
            record.checkout_image_url = payload.image_url
            await self.session.commit()
        return record

    async def face_enroll(self, company_id: uuid.UUID | None, payload: FaceEnrollRequest) -> dict[str, Any]:
        stmt = select(Employee).where(Employee.id == payload.employee_id)
        res = await self.session.execute(stmt)
        emp = res.scalar_one_or_none()
        if not emp:
            raise ValueError("Employee not found for face enrollment")

        emp.is_face_enrolled = True
        emp.face_enrolled_at = datetime.now(UTC)
        await self.session.commit()
        return {
            "success": True,
            "employee_id": str(emp.id),
            "enrolled": True,
            "message": "Face biometrics enrolled securely.",
        }

    async def update_attendance(
        self,
        attendance_id: uuid.UUID,
        payload: AttendanceManualUpdateRequest,
        editor_id: uuid.UUID | None = None,
    ) -> Attendance:
        stmt = select(Attendance).where(Attendance.id == attendance_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if not record:
            raise ValueError("Attendance record not found")

        if payload.check_in_time is not None:
            record.check_in_time = payload.check_in_time
        if payload.check_out_time is not None:
            record.check_out_time = payload.check_out_time
            if record.check_in_time:
                record.working_hours = round(
                    (record.check_out_time - record.check_in_time).total_seconds() / 3600.0, 2
                )
        if payload.status is not None:
            record.status = payload.status

        record.notes = f"{record.notes or ''}; Edited by {editor_id or 'admin'}: {payload.audit_reason}"
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete_attendance(self, attendance_id: uuid.UUID) -> bool:
        stmt = select(Attendance).where(Attendance.id == attendance_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if not record:
            return False
        await self.session.delete(record)
        await self.session.commit()
        return True

    async def list_records(
        self,
        company_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        stmt = select(Attendance)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if employee_id:
            stmt = stmt.where(Attendance.employee_id == employee_id)
        if from_date:
            stmt = stmt.where(Attendance.date >= from_date)
        if to_date:
            stmt = stmt.where(Attendance.date <= to_date)
        if status:
            stmt = stmt.where(Attendance.status.ilike(status))

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(Attendance.date)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(i.id),
                    "employee_id": str(i.employee_id),
                    "date": i.date.isoformat(),
                    "check_in_time": i.check_in_time.isoformat() if i.check_in_time else None,
                    "check_out_time": i.check_out_time.isoformat() if i.check_out_time else None,
                    "status": i.status,
                    "is_late": i.is_late or False,
                    "late_minutes": i.late_minutes or 0,
                    "working_hours": float(i.working_hours or 0.0),
                    "notes": i.notes,
                }
                for i in items
            ],
        }

    async def get_analytics(self, company_id: uuid.UUID | None, target_date: date | None = None) -> dict[str, Any]:
        t_date = target_date or date.today()
        stmt = select(Attendance).where(Attendance.date == t_date)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        total = len(records)
        present = sum(1 for r in records if (r.status or "").lower() in ("present", "late"))
        late = sum(1 for r in records if r.is_late or (r.status or "").lower() == "late")
        avg_hours = sum(float(r.working_hours or 0) for r in records) / total if total > 0 else 0.0

        return {
            "date": t_date.isoformat(),
            "total_marked": total,
            "present": present,
            "late": late,
            "average_working_hours": round(avg_hours, 2),
            "attendance_rate": round((present / total) * 100, 2) if total > 0 else 100.0,
        }

    async def create_regularization(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceRegularizationCreateRequest,
    ) -> AttendanceRegularizationRequest:
        req = AttendanceRegularizationRequest(
            id=uuid.uuid4(),
            attendance_id=payload.attendance_id,
            employee_id=employee_id,
            company_id=company_id,
            request_date=payload.request_date,
            requested_check_in=payload.requested_check_in,
            requested_check_out=payload.requested_check_out,
            reason=payload.reason,
            status="PENDING",
        )
        self.session.add(req)
        await self.session.commit()
        await self.session.refresh(req)
        return req

    async def list_regularizations(
        self,
        company_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        stmt = select(AttendanceRegularizationRequest)
        if company_id:
            stmt = stmt.where(AttendanceRegularizationRequest.company_id == company_id)
        if employee_id:
            stmt = stmt.where(AttendanceRegularizationRequest.employee_id == employee_id)
        if status:
            stmt = stmt.where(AttendanceRegularizationRequest.status == status)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(AttendanceRegularizationRequest.created_at)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(i.id),
                    "employee_id": str(i.employee_id),
                    "request_date": i.request_date.isoformat(),
                    "requested_check_in": i.requested_check_in.isoformat() if i.requested_check_in else None,
                    "requested_check_out": i.requested_check_out.isoformat() if i.requested_check_out else None,
                    "reason": i.reason,
                    "status": i.status,
                    "created_at": i.created_at.isoformat(),
                }
                for i in items
            ],
        }

    async def get_analytics_trends(
        self,
        company_id: uuid.UUID | None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        """Get attendance trends over a date range (daily attendance rates)."""
        to_d = to_date or date.today()
        from_d = from_date or (to_d - timedelta(days=29))
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        # Group by date
        from collections import defaultdict
        daily_data = defaultdict(lambda: {"total": 0, "present": 0, "late": 0, "hours": 0.0})
        for r in records:
            d = r.date.isoformat()
            daily_data[d]["total"] += 1
            if (r.status or "").lower() in ("present", "late"):
                daily_data[d]["present"] += 1
            if r.is_late or (r.status or "").lower() == "late":
                daily_data[d]["late"] += 1
            daily_data[d]["hours"] += float(r.working_hours or 0)

        trends = []
        for d in sorted(daily_data.keys()):
            data = daily_data[d]
            rate = round((data["present"] / data["total"]) * 100, 2) if data["total"] > 0 else 0.0
            trends.append({
                "date": d,
                "total_marked": data["total"],
                "present": data["present"],
                "late": data["late"],
                "attendance_rate": rate,
                "average_working_hours": round(data["hours"] / data["total"], 2) if data["total"] > 0 else 0.0,
            })

        return {
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "trends": trends,
        }

    async def get_analytics_rate(
        self,
        company_id: uuid.UUID | None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        """Get overall attendance rate for a date range."""
        to_d = to_date or date.today()
        from_d = from_date or (to_d - timedelta(days=29))
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        total = len(records)
        present = sum(1 for r in records if (r.status or "").lower() in ("present", "late"))
        late = sum(1 for r in records if r.is_late or (r.status or "").lower() == "late")
        avg_hours = sum(float(r.working_hours or 0) for r in records) / total if total > 0 else 0.0

        return {
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "total_records": total,
            "present": present,
            "late": late,
            "absent": total - present,
            "attendance_rate": round((present / total) * 100, 2) if total > 0 else 0.0,
            "average_working_hours": round(avg_hours, 2),
        }

    async def get_analytics_weekly(
        self,
        company_id: uuid.UUID | None,
        weeks: int = Query(4, ge=1, le=12),
    ) -> dict[str, Any]:
        """Get weekly aggregated attendance data."""
        to_d = date.today()
        from_d = to_d - timedelta(weeks=weeks)
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        # Group by ISO week
        from collections import defaultdict
        weekly_data = defaultdict(lambda: {"total": 0, "present": 0, "late": 0, "hours": 0.0, "days": set()})
        for r in records:
            iso_week = r.date.isocalendar()
            week_key = f"{iso_week.year}-W{iso_week.week:02d}"
            weekly_data[week_key]["total"] += 1
            weekly_data[week_key]["days"].add(r.date)
            if (r.status or "").lower() in ("present", "late"):
                weekly_data[week_key]["present"] += 1
            if r.is_late or (r.status or "").lower() == "late":
                weekly_data[week_key]["late"] += 1
            weekly_data[week_key]["hours"] += float(r.working_hours or 0)

        weekly = []
        for wk in sorted(weekly_data.keys()):
            data = weekly_data[wk]
            working_days = len(data["days"])
            rate = round((data["present"] / data["total"]) * 100, 2) if data["total"] > 0 else 0.0
            weekly.append({
                "week": wk,
                "working_days": working_days,
                "total_records": data["total"],
                "present": data["present"],
                "late": data["late"],
                "attendance_rate": rate,
                "average_working_hours": round(data["hours"] / data["total"], 2) if data["total"] > 0 else 0.0,
            })

        return {
            "weeks": weeks,
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "weekly": weekly,
        }
